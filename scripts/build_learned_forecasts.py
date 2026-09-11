"""Pooled gradient boosting, purged chronological tests, and an abstention gate.

Price-only research model. No news, revised fundamentals or current macro values
are inserted into past features. Current-universe survivorship bias remains.
"""
from __future__ import annotations
import hashlib
import json
import os
os.environ.setdefault('OMP_NUM_THREADS', '2')
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from build_forecasts import atomic_json, age_days

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'pooled-hgb-price-v1'
HORIZONS = (21, 84, 252)
FEATURES = ['r5','r21','r63','r126','ma20','ma50','ma200','vol21','vol84','drawdown','volumeRatio','market21','market63','relative63']
PARAMS = dict(max_iter=60, max_leaf_nodes=15, learning_rate=.05,
              min_samples_leaf=40, l2_regularization=10, early_stopping=False, random_state=17)

def feature_frame(rows):
    f = pd.DataFrame(rows).drop_duplicates('date').sort_values('date').set_index('date')
    p = pd.to_numeric(f.close, errors='coerce'); p = p.where(p>0)
    x = pd.DataFrame(index=f.index)
    for n in (5,21,63,126): x['r'+str(n)] = p/p.shift(n)-1
    for n in (20,50,200): x['ma'+str(n)] = p/p.rolling(n).mean()-1
    for n in (21,84): x['vol'+str(n)] = p.pct_change(fill_method=None).rolling(n).std()*np.sqrt(252)
    x['drawdown'] = p/p.rolling(252).max()-1
    vol = pd.to_numeric(f.get('volume', pd.Series(index=f.index,dtype=float)), errors='coerce')
    x['volumeRatio'] = vol/vol.rolling(63).mean().replace(0,np.nan)
    x['close'] = p
    return x.replace([np.inf,-np.inf],np.nan).iloc[251:]

def trend(x,h):
    momentum=(.5*np.log1p(x.r21)/21+.3*np.log1p(x.r63)/63+.2*np.log1p(x.r126)/126)
    return np.clip(.35*momentum,-.6/252,.6/252)*63*(1-np.exp(-h/63))

def load_frames(root, now):
    frames={}; hashes={}
    for path in sorted((root/'prices/history').glob('*.json')):
        raw=path.read_bytes(); record=json.loads(raw)
        rows=[q for q in record.get('prices',[]) if q.get('date','')<=now[:10]]
        if len(rows)<600: continue
        f=feature_frame(rows)
        if f.empty: continue
        frames[path.stem]=f; hashes[path.stem]=hashlib.sha256(raw).hexdigest()
    if 'SPY' not in frames: return {},hashes
    market=frames['SPY']
    for f in frames.values():
        f['market21']=market.r21.reindex(f.index)
        f['market63']=market.r63.reindex(f.index)
        f['relative63']=f.r63-f.market63
    return frames,hashes

def examples(frames,h):
    chunks=[]
    for symbol,f in frames.items():
        q=f.copy(); q['y']=np.log(q.close.shift(-h)/q.close)
        q['targetDate']=pd.Series(q.index,index=q.index).shift(-h)
        q['symbol']=symbol; q['origin']=q.index; q['trend']=trend(q,h)
        # Common calendar alignment, not a symbol-specific sampling phase.
        chunks.append(q)
    return pd.concat(chunks).replace([np.inf,-np.inf],np.nan).dropna(subset=FEATURES+['y','targetDate'])

def fit_at(data,calendar,origin,h):
    pos=calendar.index(origin); cut=calendar[max(0,pos-h-126)]
    train=data[(data.targetDate<cut)&(data.origin<cut)]
    cal=data[(data.origin>=cut)&(data.targetDate<origin)]
    # Fit on every 21st common trading date. No random row splitting.
    allowed=set(calendar[::21]);train=train[train.origin.isin(allowed)]
    if len(train)<3000 or train.symbol.nunique()<20 or len(cal)<500: return None
    model=HistGradientBoostingRegressor(**PARAMS).fit(train[FEATURES],train.y)
    errors=cal.y.to_numpy()-model.predict(cal[FEATURES])
    lo,hi=np.quantile(errors,[.1,.9])
    return model,float(min(lo,0)),float(max(hi,0)),dict(trainRows=len(train),calibrationRows=len(cal),
        trainTargetThrough=str(train.targetDate.max()),calibrationTargetThrough=str(cal.targetDate.max()),
        origin=origin,trainCutoff=cut)

def metrics(rows):
    if not rows: return dict(n=0,dates=0)
    d=pd.DataFrame(rows); actual=np.expm1(d.y); pred=np.expm1(d.pred)
    # Errors are return percentage points, not accuracy probabilities.
    return dict(n=len(d),dates=int(d.origin.nunique()),mae=float(np.mean(abs(actual-pred))),
        noChangeMae=float(np.mean(abs(actual))),trendMae=float(np.mean(abs(actual-np.expm1(d.trend)))),
        directionAccuracy=float(np.mean(np.sign(d.y)==np.sign(d.pred))),
        alwaysUpAccuracy=float(np.mean(d.y>0)),rangeCoverage=float(np.mean((d.y>=d.low)&(d.y<=d.high))),
        firstDate=str(d.origin.min()),lastDate=str(d.origin.max()))

def qualifies(m):
    return m.get('dates',0)>=4 and m['mae']<.98*min(m['noChangeMae'],m['trendMae']) and m['directionAccuracy']>=m['alwaysUpAccuracy'] and m['rangeCoverage']>=.60

def build(root=ROOT,now=None):
    now=now or datetime.now(timezone.utc).isoformat(timespec='seconds')
    frames,hashes=load_frames(root,now)
    result=dict(schemaVersion=1,model=MODEL,generatedAt=now,status='missing',stocks={},validation={},
        features=FEATURES,parameters=PARAMS,sklearnVersion=sklearn.__version__,historyHashes=hashes,
        limitations=['현재 수집 종목 기준: 상장폐지 종목을 포함한 생존편향 보정 전',
          '가격·거래량 모델: 뉴스·실적·거시경제를 학습한 모델 아님',
          '종목 간 상관이 있으므로 종목 수 × 날짜 수를 독립 표본으로 해석하면 안 됨',
          '범위는 과거 오차 10·90 분위수이며 미래 포함 확률 보장 아님',
          '종목별 통과 조건은 사후 선별: 통과 종목 집합의 실전 성과는 별도 검증 필요',
          '배당·거래비용·체결을 반영한 매매전략 검증 아님'],
        method='Fixed pooled HGB; 6 disjoint outcome dates; purged train/calibration/test; no hyperparameter search; return-MAE versus no-change and trend-decay.')
    if not frames:
        atomic_json(root/'ml/latest.json',result);print('ML: usable SPY and stock history required');return result
    calendar=list(frames['SPY'].index);latest=calendar[-1]
    for h in HORIZONS:
        data=examples(frames,h);outcomes=[];folds=[]
        last=len(calendar)-h-2
        origins=[calendar[j] for j in sorted(last-k*max(h,126) for k in range(6)) if j>=h+400]
        print(f'ML {h}: {len(data)} labeled rows, {len(origins)} chronological folds',flush=True)
        for origin in origins:
            trained=fit_at(data,calendar,origin,h)
            if not trained:continue
            model,lo,hi,meta=trained;test=data[data.origin==origin].copy()
            if test.empty:continue
            test['pred']=model.predict(test[FEATURES]);test['low']=test.pred+lo;test['high']=test.pred+hi
            outcomes.extend(test[['symbol','origin','targetDate','y','trend','pred','low','high']].to_dict('records'));folds.append(meta)
        overall=metrics(outcomes);global_ok=qualifies(overall)
        result['validation'][str(h)]=dict(**overall,passed=global_ok,folds=folds)
        trained=fit_at(data,calendar,latest,h)
        if not trained:continue
        model,lo,hi,meta=trained
        # Retain tree weights locally for reproduction; the browser reads results only.
        import joblib
        (root/'ml/models').mkdir(parents=True,exist_ok=True)
        joblib.dump(model,root/'ml/models'/f'{h}.joblib')
        for symbol,f in frames.items():
            current=f.iloc[[-1]];asof=str(current.index[-1]);age=age_days(asof,now)
            if current[FEATURES].isna().any(axis=None):continue
            pred=float(model.predict(current[FEATURES])[0]);price=float(current.close.iloc[0])
            own=metrics([q for q in outcomes if q['symbol']==symbol])
            fresh=age is not None and 0<=age<=5 and asof==latest
            valid_range=abs(pred)<2 and abs(pred+lo)<3 and abs(pred+hi)<3
            passed=global_ok and qualifies(own) and fresh and valid_range
            reasons=[]
            if not fresh:reasons.append('최신 가격 정렬 확인 필요')
            if not global_ok:reasons.append('전체 검증에서 단순 예측 대비 우위 미확인')
            if not qualifies(own):reasons.append('종목별 검증 기준 미충족')
            if not valid_range:reasons.append('예측 범위 비정상')
            forecast=dict(horizon=h,anchor=price,base=price*np.exp(pred),bear=price*np.exp(pred+lo),bull=price*np.exp(pred+hi),
                **{'return':float(np.expm1(pred))},direction='up' if pred>np.log(1.02) else 'down' if pred<np.log(.98) else 'neutral',
                learned=True,logReturn=pred,lowLogReturn=pred+lo,highLogReturn=pred+hi)
            entry=result['stocks'].setdefault(symbol,dict(asOf=asof,price=price,predictions={}))
            entry['predictions'][str(h)]=dict(status='eligible' if passed else 'withheld',reasons=reasons,
                forecast=forecast,validation=own,training=meta)
        atomic_json(root/'ml/validation'/f'{h}.json',dict(model=MODEL,generatedAt=now,folds=folds,outcomes=outcomes))
    result['status']='trained';result['asOf']=latest
    # First publication per model/symbol/origin/horizon is preserved, including withheld status.
    archive=root/'ml/archive'/f'{latest}.json'
    prior=json.loads(archive.read_text()) if archive.exists() else dict(model=MODEL,issuedAt=now,stocks={})
    for symbol,entry in result['stocks'].items():
        if entry['asOf']!=latest:continue
        old=prior['stocks'].setdefault(symbol,dict(asOf=latest,price=entry['price'],predictions={}))
        for h,pred in entry['predictions'].items():old['predictions'].setdefault(h,pred)
        result['stocks'][symbol]=old
    atomic_json(archive,prior);atomic_json(root/'ml/latest.json',result)
    print('ML trained:',len(result['stocks']),'symbols; eligible:',sum(p['status']=='eligible' for e in result['stocks'].values() for p in e['predictions'].values()),flush=True)
    return result

if __name__=='__main__':build()
