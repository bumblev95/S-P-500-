"""Two frozen hypotheses using new raw relative strength, never service data."""
import os
os.environ.setdefault('OMP_NUM_THREADS', '2')
import argparse, gzip, hashlib, json, pickle
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from collect_relative_inputs import FOLDER, digest
from research_joint_indicator import date_weights, label, validate_source
from research_indicator_blends import extended_score, blend_gates

CONTROLS=['noChange','priceOnly','simpleTrend','absolute_control']
NAMES={"noChange":"가격 불변","priceOnly":"가격 패턴 기준","simpleTrend":"단순 가격 추세",
       "absolute_control":"절대 추세 대조군","relative_expert":"시장·업종 상대 강도",
       "relative_half":"상대 강도 50:50","relative_stack":"과거 확정 오차 조합",
       "relative_bear_route":"시장 약세 시 역할 전환"}

def matured(rows, origin):
    return [r for r in rows if r['origin']<origin and r['targetDate']<origin]

def validate(source, snapshot, protocol, universe):
    validate_source(source, protocol)
    for h in protocol['horizons']:
        rows=source['stocks'][str(h)]['outcomes']; seen=set()
        dates=sorted({r['origin'] for r in rows})
        for a,b in zip(dates,dates[1:]):
            if max(r['targetDate'] for r in rows if r['origin']==a)>=b:
                raise ValueError('Overlapping future intervals in source')
        for r in rows:
            key=(r['origin'],universe['members'][r['symbol']]['cik'])
            if key in seen: raise ValueError('Duplicate CIK/date')
            seen.add(key)
    for f in snapshot['features'].values():
        for k in ['ownThrough','marketThrough','sectorThrough','residualThrough']:
            if f[k] is not None and f[k]>=f['origin']:
                raise ValueError('Future raw-price feature')
    if snapshot['sourceHash']!=protocol['sourceHash']:
        raise ValueError('Source mismatch')

def matrix(rows, features, relative):
    out=[]
    for r in rows:
        f=features[r['symbol']+'|'+r['origin']]
        values=[float(np.log(r[k])) for k in ('priceOnly','environment','balanced','independentReturn','secDynamics')]
        values+=f['absolute'] if f['usable'] else [None]*14
        if relative:values+=f['relative'] if f['usable'] else [None]*11
        out.append([np.nan if v is None else v for v in values])
    return np.array(out,dtype=float)

def predict_expert(train,test,features,protocol,relative):
    usable=[r for r in train if features[r['symbol']+'|'+r['origin']]['usable']]
    values=np.array([r['priceOnly'] for r in test]); y=np.array([r['y'] for r in train])
    mask=np.array([features[r['symbol']+'|'+r['origin']]['usable'] for r in test])
    if len({r['origin'] for r in usable})<3:
        return values,dict(fallbackRows=len(test),trainingRows=len(usable),clippedRows=0,modelFallback=True)
    model=HistGradientBoostingRegressor(loss='absolute_error',**protocol['regressor'])
    model.fit(matrix(usable,features,relative),[r['y'] for r in usable],sample_weight=date_weights(usable))
    predictions=model.predict(matrix(test,features,relative))
    clipped=np.clip(predictions,y.min(),y.max())
    values[mask]=clipped[mask]
    return values,dict(fallbackRows=int((~mask).sum()),trainingRows=len(usable),
        clippedRows=int(np.sum((predictions!=clipped)&mask)),modelFallback=False,
        targetThrough=max(r['targetDate'] for r in usable),modelHash=digest(pickle.dumps(model,protocol=4)))

def choose_weight(history,origin):
    past=matured(history,origin); dates=sorted({r['origin'] for r in past})
    info=dict(historyRows=len(past),historyDates=len(dates),targetThrough=max((r['targetDate'] for r in past),default=None))
    if len(dates)<3:return dict(weight=0.,status='fallback_priceOnly',**info)
    y=np.array([r['y'] for r in past]); a=np.array([r['methods']['priceOnly']['value'] for r in past])
    b=np.array([r['methods']['relative_expert']['value'] for r in past]); w=date_weights(past)
    losses=[]
    for weight in [0.,.25,.5,.75,1.]:
        pred=(1-weight)*a+weight*b
        pred=np.array([np.clip(v,*r['maturedBounds']) if r.get('inputUsable',True) else a[i]
                       for i,(v,r) in enumerate(zip(pred,past))])
        losses.append((float(np.average(abs(pred/y-1)+abs(pred-y),weights=w)),weight))
    loss,weight=min(losses)
    return dict(weight=weight,status='selected_matured_oos',loss=loss,gridLosses=losses,**info)

def weighted_score(rows,name):
    m=extended_score(rows,name);weights=date_weights(rows)
    actual=np.array([r['y'] for r in rows]);truth=label(actual)
    pred=np.array([r['methods'][name]['value'] for r in rows]);direction=label(pred)
    avg=lambda a,w=weights:float(np.average(a,weights=w))
    pooled={k:m[k] for k in ['directionAccuracy','returnDirectionAccuracy','balancedDirectionAccuracy',
        'upRecall','downRecall','flatRecall','downPrecision','downPrevalence','alwaysUpAccuracy','falseDownWarningRate']}
    recalls={c:avg(direction[truth==c]==c,weights[truth==c]) if np.any(truth==c) else None for c in [-1,0,1]}
    down=direction==-1;not_down=truth!=-1
    m.update(directionAccuracy=avg(direction==truth),returnDirectionAccuracy=avg(direction==truth),
        balancedDirectionAccuracy=float(np.mean([v for v in recalls.values() if v is not None])),
        upRecall=recalls[1],downRecall=recalls[-1],flatRecall=recalls[0],
        downPrecision=avg(truth[down]==-1,weights[down]) if down.any() else None,
        downPrevalence=avg(truth==-1),alwaysUpAccuracy=avg(truth==1),
        falseDownWarningRate=avg(down[not_down],weights[not_down]) if not_down.any() else None,
        pooledAllRows=pooled,metricWeighting='Equal total weight per origin date')
    def quantile(values):
        order=np.argsort(values,kind='stable');mass=np.cumsum(weights[order])/weights.sum()
        return float(values[order[min(np.searchsorted(mass,.9),len(order)-1)]])
    m.update(pooledP90Mape=m['p90Mape'],pooledP90ReturnError=m['p90ReturnError'],
        p90Mape=quantile(abs(pred/actual-1)),p90ReturnError=quantile(abs(pred-actual)),
        logMae=avg(abs(np.log(pred/actual))))
    for day,stats in m['byDate'].items():
        one=extended_score([r for r in rows if r['origin']==day],name)
        stats.update({k:one[k] for k in ['upRecall','downRecall','flatRecall','downPrecision',
            'balancedDirectionAccuracy','falseDownWarningRate','downWarnings','falseDownWarnings','p90Mape','p90ReturnError']})
    return m

def diagnostics(rows):
    y=np.array([r['y'] for r in rows]);w=date_weights(rows)
    a=np.log([r['methods']['priceOnly']['value'] for r in rows])-np.log(y)
    b=np.log([r['methods']['relative_expert']['value'] for r in rows])-np.log(y)
    a-=np.average(a,weights=w);b-=np.average(b,weights=w)
    corr=np.average(a*b,weights=w)/np.sqrt(np.average(a*a,weights=w)*np.average(b*b,weights=w))
    return dict(logErrorCorrelation=float(corr), probability=dict(status='not_applicable',brier=None,logLoss=None,
        reason='Numeric median forecasts and blends emit no class probabilities; none borrowed from classifier.'),
        abstentionFraction=0., noTradePerformanceEvaluated=True)

def evaluate(source,snapshot,protocol):
    features=snapshot['features'];out={};saved={}
    for h in protocol['horizons']:
        rows=source['stocks'][str(h)]['outcomes'];dates=sorted({r['origin'] for r in rows});start=dates[len(dates)//2]
        history=[];evaluation=[];folds=[]
        for origin in dates:
            train=matured(rows,origin); test=[r for r in rows if r['origin']==origin]
            if len({r['origin'] for r in train})<3:
                folds.append(dict(origin=origin,status='warmup_insufficient'));continue
            expert,info=predict_expert(train,test,features,protocol,True)
            control,control_info=predict_expert(train,test,features,protocol,False)
            settings=choose_weight(history,origin)
            bounds=[min(r['y'] for r in train),max(r['y'] for r in train)]
            routed=0;fallback=0;clipped_trend=0;clipped_stack=0
            for i,r in enumerate(test):
                f=features[r['symbol']+'|'+origin];price=r['priceOnly']
                use_route=f['usable'] and f['absolute'][9]<0 and expert[i]<.98
                routed+=int(use_route);fallback+=int(not f['usable'])
                raw_trend=float(np.exp(h/126*f['absolute'][1])) if f['usable'] else price
                trend=float(np.clip(raw_trend,*bounds)) if f['usable'] else price
                clipped_trend+=int(trend!=raw_trend)
                raw_stack=(1-settings['weight'])*price+settings['weight']*expert[i]
                stack=float(np.clip(raw_stack,*bounds)) if f['usable'] else price
                clipped_stack+=int(stack!=raw_stack)
                values=dict(noChange=1.,priceOnly=price,simpleTrend=trend,absolute_control=control[i],relative_expert=expert[i],
                    relative_half=.5*price+.5*expert[i], relative_stack=stack,
                    relative_bear_route=expert[i] if use_route else price)
                record=dict(symbol=r['symbol'],origin=origin,targetDate=r['targetDate'],y=r['y'],regime=r['regime'],
                    inputUsable=f['usable'],sectorAvailable=f['sectorAvailable'],bearRouted=bool(use_route),maturedBounds=bounds,
                    methods={k:dict(value=float(v),direction=int(label(v))) for k,v in values.items()})
                history.append(record)
                if origin>=start:evaluation.append(record)
            folds.append(dict(origin=origin,status='evaluation' if origin>=start else 'oos_warmup',
                fitRows=len(train),fitDates=len({r['origin'] for r in train}),fitTargetThrough=max(r['targetDate'] for r in train),
                expert=info,control=control_info,settings=settings,testRows=len(test),fallbackRows=fallback,
                bearRoutedRows=routed,trendClippedRows=clipped_trend,stackClippedRows=clipped_stack))
            print(h,origin,'fit',len(train),'test',len(test),'stack',settings['weight'],flush=True)
        metrics={name:weighted_score(evaluation,name) for name in NAMES}
        checks={name:blend_gates(metrics[name],metrics['priceOnly'],metrics['noChange'],protocol) for name in protocol['candidates']}
        for name,c in checks.items():
            m=metrics[name]
            c.update(falseWarnings=m['falseDownWarningRate']<=metrics['priceOnly']['falseDownWarningRate'],
                simpleTrend=m['dateMeanMape']<=metrics['simpleTrend']['dateMeanMape'] and
                            m['dateMeanReturnMae']<=metrics['simpleTrend']['dateMeanReturnMae'],
                absoluteControl=m['dateMeanMape']<=metrics['absolute_control']['dateMeanMape'] and
                                m['dateMeanReturnMae']<=metrics['absolute_control']['dateMeanReturnMae'])
        by_regime={regime:{name:weighted_score([r for r in evaluation if r['regime']==regime],name) for name in NAMES}
                   for regime in sorted({r['regime'] for r in evaluation})}
        out[str(h)]=dict(evaluation=metrics,regimes=by_regime,checks=checks,folds=folds,
            historicalPassed={n:all(v for k,v in c.items() if k!='prospective') for n,c in checks.items()},
            passed={n:all(c.values()) for n,c in checks.items()},selected=None,
            evaluatedDates=sorted({r['origin'] for r in evaluation}),diagnostics=diagnostics(evaluation),
            coverage=dict(totalRows=len(evaluation),usableRows=sum(r['inputUsable'] for r in evaluation),
                sectorRows=sum(r['sectorAvailable'] for r in evaluation),fallbackRows=sum(not r['inputUsable'] for r in evaluation)),
            stackStatus=dict(Counter(f['settings']['status'] for f in folds if f['status']=='evaluation')),
            predictionsHash=digest(json.dumps(evaluation,sort_keys=True).encode()))
        saved[str(h)]=dict(historicalOOS=history,pairedEvaluation=evaluation)
    return out,saved

def report(result):
    fmt=lambda v:'—' if v is None else f'{v*100:.2f}'
    lines=['# 시장·업종 상대 강도와 결합 연구', '',f"등록: {result['registeredAt']} · 실행: {result['generatedAt']}", '',
        '가설 A: 새 원시 가격으로 절대 추세와 시장·업종 상대 강도를 분리. 가설 B: 해당 전문가와 가격 패턴의 단순 평균·과거 확정 오차 조합·시장 약세 시 역할 전환. 결과 후 튜닝 없음.', '',
        '최신 main의 가격·모델 자료가 이전 연구와 달라 새 기준값을 동일 표본으로 다시 계산했다. 과거 18개/16개 origin 집합은 그대로다. 새 실전 증거나 웹 서비스 AI와의 직접 우위 비교가 아니다.', '']
    for h,q in result['horizons'].items():
        lines += [f"## {h}거래일",'',f"{q['coverage']} · {len(q['evaluatedDates'])}개 날짜",'',
            '| 방법 | 가격 MAPE % | 수익률 MAE %p | 방향 적중 % | 균형 방향 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % | 잘못된 경고율 % |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
        for name,m in q['evaluation'].items():
            lines.append('| '+NAMES[name]+' | '+' | '.join(fmt(m[k]) for k in ['dateMeanMape','dateMeanReturnMae','directionAccuracy',
                'balancedDirectionAccuracy','upRecall','downRecall','downPrecision','falseDownWarningRate'])+' |')
        lines += ['',f"항상 상승 적중률 {fmt(q['evaluation']['priceOnly']['alwaysUpAccuracy'])}%. 로그 오차 상관 {q['diagnostics']['logErrorCorrelation']:.3f}. 수익률 부호와 방향은 동일 정의(±2% 중립).",'']
        for name,c in q['checks'].items():lines.append(f"- {NAMES[name]}: 미통과 항목 {', '.join(k for k,v in c.items() if not v)}.")
        lines += ['']
    lines += ['## 해석과 재현','',
        '- 표의 오차·방향·포착·경고는 날짜별 동일 가중. 기존 비교용 전체 표본 단순 집계도 pooledAllRows에 별도 보존했다. 큰 오차·날짜별 결과·시장 상황별 성적은 results.json에 저장했다. 보류율0%; 결측 대체 행도 전체 성적에 포함했다.',
        '- 숫자 전문가·결합은 확률을 출력하지 않으므로 Brier·logloss는 해당 없음으로 기록했다. 미교정 점수를 확률로 쓰지 않았다.',
        '- 현재 구성 종목/업종과 수정된 조정가격을 사용한 생존·분류·자료 수정 편향이 남는다. XLC·XLRE의 상장 전 자료를 만들어내지 않았다. 잔차 강도 논문의 방법을 그대로 재현하거나 그 수익을 달성했다고 주장하지 않는다.',
        '- 학습·비중 선택은 각 origin 전 결과 확정 표본만 사용. 같은 horizon 결과 구간의 겹침과 CIK/date 중복을 검증했다. 적은 날짜와 시장 상관으로 통계 신뢰는 제한된다.',
        '- 단기 진입·보유 규칙과 별도인 장기 예측 연구. 거래 체결·비용·회전율·낙폭을 검증하지 않아 매매 성과를 주장하지 않는다.',
        '- 새 발행 기록은 별도로 보존해야 한다. 이번 main의 최신 전망 origin은 2026-10-05로 발행 시점과 다르므로 소급 예측을 새 발행으로 넣지 않았다.',
        '- UI·서비스 예측·순위·실전/모의운용·승격 정책 변경 없음. 후보 선택·자동 병합 없음.',
        '- 다음 연구: 시점별 구성·업종 및 상장폐지 포함 자료 확보; 종료 수익률과 기간 중 낙폭 목표 분리. 새 후보가 원시 가격을 사용해도 오차 상관이 낮아지지 않으면 평균/스태킹 반복을 우선하지 않는다.', '',
        '재현: `python scripts/research_relative_blends.py` · 입력 수집: `python scripts/collect_relative_inputs.py` · 검증: `python scripts/test_relative_blends.py`', '',
        '근거: [Residual Momentum, 2011](https://repub.eur.nl/pub/22252) · [공식 회귀 문서](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html)', '']
    return '\n'.join(lines)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--folder',type=Path,default=FOLDER)
    args=parser.parse_args();folder=args.folder
    protocol=json.loads((folder/'PROTOCOL.json').read_text());raw=gzip.decompress((folder/'sources/environment.json.gz').read_bytes())
    source=json.loads(raw);snapshot=json.loads(gzip.decompress((folder/'sources/raw-features.json.gz').read_bytes()))
    universe=json.loads((folder/'sources/universe.json').read_text())
    if digest(raw)!=protocol['sourceHash']:raise ValueError('Hash mismatch')
    if snapshot['protocolHash']!=digest((folder/'PROTOCOL.json').read_bytes()):raise ValueError('Protocol changed after collection')
    validate(source,snapshot,protocol,universe)
    horizons,predictions=evaluate(source,snapshot,protocol)
    hashes={p.name:digest(p.read_bytes()) for p in [Path(__file__),Path(__file__).with_name('collect_relative_inputs.py'),
        Path(__file__).with_name('research_joint_indicator.py'),Path(__file__).with_name('research_indicator_blends.py')]}
    result=dict(version=protocol['version'],registeredAt=protocol['registeredAt'],generatedAt=datetime.now(timezone.utc).isoformat(),
        sourceMainCommit=protocol['sourceMainCommit'],parentResearchCommit=protocol['parentResearchCommit'],
        sourceHash=digest(raw),featureSnapshotHash=digest((folder/'sources/raw-features.json.gz').read_bytes()),
        universeHash=digest((folder/'sources/universe.json').read_bytes()),
        protocolHash=digest((folder/'PROTOCOL.json').read_bytes()),codeHashes=hashes,sklearnVersion=sklearn.__version__,
        uiChanged=False,serviceForecastChanged=False,historicalHoldoutRevisited=True,selected=None,horizons=horizons,
        prospective=dict(issuedForecasts=0,reason='Latest saved base forecasts asOf2026-10-05; no timely full fresh base snapshot. Historical replays never entered as live issues.'))
    (folder/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (folder/'predictions.json.gz').write_bytes(gzip.compress(json.dumps(predictions,sort_keys=True,ensure_ascii=False,allow_nan=False).encode(),mtime=0))
    (folder/'RESULTS.md').write_text(report(result))
    print('Research saved; no UI/service changes.',flush=True)

if __name__=='__main__':main()
