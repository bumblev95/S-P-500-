"""Chronological pooled spot-price research. No derivative prices or present-day supply in past features."""
import os
os.environ.setdefault('OMP_NUM_THREADS','2')
import json, math, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from build_forecasts import atomic_json
ROOT=Path(__file__).resolve().parents[1]
HORIZONS=(30,120,365)
MODEL='spot-hgb-median-v1.2'
# Verified names are checked again in the response; unsupported tickers keep CoinGecko history.
YAHOO={'BTC':('BTC-USD','bitcoin'),'ETH':('ETH-USD','ethereum'),'SOL':('SOL-USD','solana'),'BNB':('BNB-USD','bnb'),'XRP':('XRP-USD','xrp'),'DOGE':('DOGE-USD','dogecoin'),'LINK':('LINK-USD','chainlink'),'AVAX':('AVAX-USD','avalanche')}
FEATURES=['return7','return30','return90','return180','vol30','vol90','volRatio','distance20','distance50','distance200','drawdown90','range90','upDays30','bitcoin30','bitcoin90','relativeBitcoin30']
def clean(rows):
    found={}
    for r in rows:
        try:
            d=datetime.fromisoformat(r['date']).date().isoformat();p=float(r['close'])
            if math.isfinite(p) and p>0:found[d]=dict(date=d,close=p)
        except (ValueError,KeyError,TypeError):pass
    return [found[d] for d in sorted(found)]
def continuous(rows):
    return all((datetime.fromisoformat(b['date'])-datetime.fromisoformat(a['date'])).days==1 for a,b in zip(rows,rows[1:]))
def yahoo_rows(raw,ticker,name,today):
    result=raw.get('chart',{}).get('result') or []
    if not result:raise ValueError('No Yahoo spot series')
    r=result[0];m=r['meta']
    if m.get('symbol')!=ticker or m.get('currency')!='USD' or m.get('instrumentType')!='CRYPTOCURRENCY' or name not in (m.get('shortName','')+' '+m.get('longName','')).lower():
        raise ValueError('Spot asset identity mismatch')
    rows=[]
    for t,p in zip(r.get('timestamp',[]),r['indicators']['quote'][0]['close']):
        d=datetime.fromtimestamp(t,timezone.utc).date().isoformat()
        if d<today:rows.append(dict(date=d,close=p))
    return clean(rows)
def aligned(rows,cg):
    if not rows or not cg:return False
    target={r['date']:r['close'] for r in cg};overlap=[abs(r['close']/target[r['date']]-1) for r in rows[-60:] if r['date'] in target]
    return len(overlap)>=20 and float(np.median(overlap))<.05 and max(overlap)<.25
def histories(root,data,now,download=True):
    folder=root/'crypto/research-history';folder.mkdir(parents=True,exist_ok=True)
    today=now.date().isoformat();out={};errors=[];halt=False
    for sym,e in data['coins'].items():
        cg=clean(e.get('spotHistory',[]));path=folder/(sym+'.json')
        cached=json.loads(path.read_text()) if path.exists() else {};rows=cached.get('prices',[])
        target_date=cg[-1]['date'] if cg else None
        attempt_needed=cached.get('checkedDate')!=today or (rows and rows[-1]['date']!=target_date and cached.get('attemptedTarget')!=target_date)
        if sym in YAHOO and download and not halt and attempt_needed and not (cached.get('attemptedDate')==today and cached.get('attemptedTarget')==target_date):
            ticker,name=YAHOO[sym]
            try:
                req=Request('https://query1.finance.yahoo.com/v8/finance/chart/'+ticker+'?range=10y&interval=1d',headers={'User-Agent':'CryptoResearchDashboard/1.0'})
                with urlopen(req,timeout=20) as response:raw=json.load(response)
                candidate=yahoo_rows(raw,ticker,name,today)
                if not aligned(candidate,cg):raise ValueError('Yahoo / CoinGecko date or price alignment failed')
                rows=candidate;cached=dict(source='Yahoo Finance spot daily USD',ticker=ticker,checkedDate=today,attemptedDate=today,attemptedTarget=target_date,prices=rows)
                atomic_json(path,cached)
            except Exception as ex:
                if isinstance(ex,HTTPError) and ex.code in (401,403,429):halt=True
                errors.append(sym+': '+str(ex))
                cached.update(attemptedDate=today,attemptedTarget=target_date)
                atomic_json(path,cached)
        use=clean(rows) if aligned(rows,cg) else cg
        source=cached.get('source') if use and use!=cg else 'CoinGecko UTC daily spot'
        # Do not bridge gaps or blend different providers into one learned return series.
        for i in range(len(use)-1,0,-1):
            if not continuous(use[i-1:i+1]):use=use[i:];break
        out[sym]=dict(rows=use,source=source)
    return out,errors

def features(rows,i,btc):
    if i<199:return None
    p=np.array([r['close'] for r in rows[i-199:i+1]],dtype=float);r=np.diff(np.log(p))
    b=btc.get(rows[i]['date'])
    if b is None:return None
    v30=float(np.std(r[-30:],ddof=1));v90=float(np.std(r[-90:],ddof=1))
    momentum=[float(np.log(p[-1]/p[-n-1])) for n in (7,30,90,180)]
    high=float(np.max(p[-90:]));low=float(np.min(p[-90:]))
    x=momentum+[v30*math.sqrt(365),v90*math.sqrt(365),v30/v90 if v90 else 1]+[float(p[-1]/np.mean(p[-n:])-1) for n in (20,50,200)]+[float(p[-1]/high-1),(float(p[-1])-low)/(high-low) if high>low else .5,float(np.mean(r[-30:]>0)),*b,momentum[1]-b[0]]
    return x if all(math.isfinite(v) for v in x) else None

def make_records(hist,h):
    br=hist.get('BTC',{}).get('rows',[]);btc={r['date']:[math.log(r['close']/br[i-30]['close']),math.log(r['close']/br[i-90]['close'])] for i,r in enumerate(br) if i>=90}
    records=[];latest={}
    for sym,item in hist.items():
        rows=item['rows']
        for i in range(199,len(rows)):
            x=features(rows,i,btc)
            if x is None:continue
            latest[sym]=dict(x=x,asOf=rows[i]['date'],anchor=rows[i]['close'])
            if i+h>=len(rows) or datetime.fromisoformat(rows[i]['date']).toordinal()%7:continue
            drift=max(-.002,min(.002,.25*(.6*x[0]/7+.4*x[1]/30)))
            records.append(dict(symbol=sym,date=rows[i]['date'],targetDate=rows[i+h]['date'],x=x,y=math.log(rows[i+h]['close']/rows[i]['close']),trend=drift*60*(1-math.exp(-h/60))))
    return records,latest

def fit(records):
    model=HistGradientBoostingRegressor(loss='absolute_error',max_iter=70,max_leaf_nodes=7,min_samples_leaf=25,l2_regularization=10,learning_rate=.06,early_stopping=False,random_state=17)
    model.fit(np.array([r['x'] for r in records]),np.array([r['y'] for r in records]));return model

def summary(rows):
    if not rows:return dict(n=0,dates=0,mape=None,noChangeMape=None,trendMape=None,directionAccuracy=None,dateWinRate=None,over10Rate=None,over25Rate=None,medianError=None,p90Error=None)
    def metric(key):return float(np.mean([r[key] for r in rows]))
    dates=sorted({r['date'] for r in rows});wins=[]
    for d in dates:
        same=[r for r in rows if r['date']==d]
        means=[np.mean([r[k] for r in same]) for k in ('error','noChange','trendError')];wins.append(means[0]<min(means[1:]))
    return dict(n=len(rows),dates=len(dates),mape=metric('error'),noChangeMape=metric('noChange'),trendMape=metric('trendError'),directionAccuracy=metric('direction'),dateWinRate=float(np.mean(wins)),firstDate=dates[0],lastDate=dates[-1],over10Rate=float(np.mean([r['error']>.1 for r in rows])),over25Rate=float(np.mean([r['error']>.25 for r in rows])),medianError=float(np.median([r['error'] for r in rows])),p90Error=float(np.quantile([r['error'] for r in rows],.9)))

def passes(m):
    return m['dates']>=6 and m['mape']<.95*min(m['noChangeMape'],m['trendMape']) and m['dateWinRate']>=.5

def research(hist,now):
    results={s:dict(source=v['source'],historyCount=len(v['rows']),firstDate=v['rows'][0]['date'] if v['rows'] else None,predictions={}) for s,v in hist.items()};global_results={}
    for h in HORIZONS:
        records,latest=make_records(hist,h);dates=sorted({r['date'] for r in records});chosen=[]
        for d in reversed(dates):
            if not chosen or (datetime.fromisoformat(chosen[-1])-datetime.fromisoformat(d)).days>=h:chosen.append(d)
            if len(chosen)==8:break
        checks=[];folds=[]
        for origin in reversed(chosen):
            train=[r for r in records if r['targetDate']<origin];test=[r for r in records if r['date']==origin]
            if len(train)<150 or len({r['date'] for r in train})<20:continue
            model=fit(train);pred=model.predict(np.array([r['x'] for r in test]))
            folds.append(dict(origin=origin,trainTargetThrough=max(r['targetDate'] for r in train),trainRows=len(train)))
            for r,v in zip(test,pred):
                v=float(v);checks.append(dict(symbol=r['symbol'],date=origin,error=abs(math.exp(v-r['y'])-1),noChange=abs(math.exp(-r['y'])-1),trendError=abs(math.exp(r['trend']-r['y'])-1),direction=float((v>0)==(r['y']>0)),residual=r['y']-v))
        total=summary(checks);total['folds']=folds;total['passed']=passes(total);global_results[str(h)]=total
        current_models={}
        for sym,out in results.items():
            m=summary([r for r in checks if r['symbol']==sym]);current=latest.get(sym);reasons=[]
            model=None;through=None
            if current:
                origin=current['asOf']
                if origin not in current_models:
                    mature=[r for r in records if r['targetDate']<origin]
                    current_models[origin]=(fit(mature),max(r['targetDate'] for r in mature)) if len(mature)>=150 else (None,None)
                model,through=current_models[origin]
            if not current or not model:reasons.append('해당 기간 학습에 필요한 완료 현물 이력 부족')
            if m['dates']<6:reasons.append('겹치지 않는 종목별 시험 시점 6개 미만')
            if not passes(total):reasons.append('전체 검증에서 단순 예측 대비 안정적 우위 미확인')
            if not passes(m):reasons.append('종목별 가격 오차·시점별 우위 기준 미충족')
            prediction=None
            if current and model:
                lr=float(model.predict(np.array([current['x']]))[0]);prediction=dict(logReturn=lr,base=current['anchor']*math.exp(lr))
                own=[r['residual'] for r in checks if r['symbol']==sym]
                if len(own)>=6:
                    low,high=np.quantile(own,[.1,.9]);prediction.update(lowLogReturn=lr+float(low),highLogReturn=lr+float(high))
            out['predictions'][str(h)]=dict(status='eligible' if not reasons else 'withheld' if prediction else 'insufficient',forecast=prediction,validation=m,reasons=reasons,trainedThrough=through)
            if current:out.update(asOf=current['asOf'],anchor=current['anchor'],features=dict(zip(FEATURES,current['x'])))
    return dict(schemaVersion=1,model=MODEL,generatedAt=now.isoformat(),coins=results,validation=global_results,method='Pooled spot-only HGB conditional median; strictly mature labels before each test origin; non-overlapping test origins per horizon. No tuning on the test set.')

def build(root=ROOT,download=True,force=False):
    now=datetime.now(timezone.utc);data=json.loads((root/'crypto/latest.json').read_text());hist,errors=histories(root,data,now,download)
    fingerprint=hashlib.sha256(json.dumps(hist,sort_keys=True).encode()).hexdigest();target=root/'crypto/learned.json'
    old=json.loads(target.read_text()) if target.exists() else {}
    if old.get('fingerprint')==fingerprint and old.get('model')==MODEL and not force:
        print('Crypto learning: unchanged completed daily history; keep original training timestamp.');return old
    result=research(hist,now);result.update(fingerprint=fingerprint,errors=errors);atomic_json(target,result)
    print('Crypto learning:',{s:{h:p['status'] for h,p in r['predictions'].items()} for s,r in result['coins'].items()},flush=True)
    return result
if __name__=='__main__':
    import sys
    build(download='--offline' not in sys.argv,force='--force' in sys.argv)
