"""E2: one predeclared quarterly-feature increment of the earlier-selected E1 Ridge."""
from bisect import bisect_right
from collections import Counter
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import hashlib,json,time
import numpy as np
from sklearn.linear_model import Ridge
from build_forecasts import atomic_json
from audit_stock_quarterly_experiment import facts_from,snapshot,FIELDS,days
from run_stock_ranking_experiment import prepare,ridge_design,train_weights,evaluate,date_uncertainty

ROOT=Path(__file__).resolve().parents[1]

def source_eligibility(audit):
    counts=Counter(r['symbol'] for r in audit['releaseControls'] if r['status']=='matched')
    return dict(earlierCandidate=audit['e1SelectionEligible'],noSourceErrors=not audit['errors'],
        noNumericMismatches=not any(r['status']=='mismatch' for r in audit['releaseControls']),
        enoughNvdaControls=counts['NVDA']>=20,enoughMsftControls=counts['MSFT']>=20)

def timeline_value(timeline,origin):
    dates,rows=timeline;j=bisect_right(dates,origin)-1
    if j<0 or rows[j] is None or not 0<=days(origin,rows[j]['periodEnd'])<=200:return [float('nan')]*len(FIELDS)
    row=rows[j]
    if row['availableThrough']>=origin:raise ValueError('Supplement publication leakage')
    return [float(row[k]) if row[k] is not None else float('nan') for k in FIELDS]

def quarter_panel(root,ds,audit):
    folder=root/'research/experiments/2026-09-13';timelines={}
    for num,(name,sha) in enumerate(sorted(audit['sourceHashes'].items())):
        path=(folder/name if name.startswith('sec-supplement/') else root/'research/source-cache'/name)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Quarter fit source hash changed')
        payload=json.loads(path.read_text());facts=facts_from(payload)
        dates=[(date.fromisoformat(d)+timedelta(days=1)).isoformat() for d in sorted({r['filed'] for r in facts})]
        rows=[]
        for origin in dates:
            row=snapshot(facts,origin)
            rows.append({k:row[k] for k in ('periodEnd','availableThrough',*FIELDS)} if row else None)
        timelines[int(payload['cik'])]=(dates,rows)
        if (num+1)%50==0:print('Built quarterly timelines:',num+1,flush=True)
    symbols={s:v['cik'] for s,v in ds['members'].items()}
    panel=np.array([timeline_value(timelines.get(symbols[r['symbol']],([],[])),r['origin']) for r in ds['meta']])
    return panel,timelines

def fit_ridge(X,Y,meta,testX,origin):
    selected=np.array([r['targetDate']<origin for r in meta])
    weights=train_weights([r for r,yes in zip(meta,selected) if yes])
    train,test=ridge_design(X[selected],testX,weights)
    return Ridge(alpha=100.,fit_intercept=True,solver='cholesky').fit(train,Y[selected],sample_weight=weights).predict(test)

def build(root=ROOT):
    folder=root/'research/experiments/2026-09-13'
    audit=json.loads((folder/'e2-input-audit.json').read_text());e1=json.loads((folder/'e1-ranking.json').read_text())
    result=dict(experiment='stock-validation-e2-quarterly-v1',startedAt=datetime.now(timezone.utc).isoformat(),
        codeHash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        protocolHash=hashlib.sha256((folder/'E2-PROTOCOL.md').read_bytes()).hexdigest(),
        inputAuditHash=hashlib.sha256((folder/'e2-input-audit.json').read_bytes()).hexdigest(),
        sourceChecks=source_eligibility(audit),additionalConfigurationsFitted=0,productionPromoted=False,
        valuationFitted=False,valuationBlock=audit['valuation']['reason'],prospective=False)
    def finish():
        result['completedAt']=datetime.now(timezone.utc).isoformat()
        atomic_json(folder/'e2-quarterly.json',result)
        lines=['# E2: 분기 실적의 순위 예측 증분 실험','',f"상태: {result['status']}. 실제 추가 학습 설정 수: {result['additionalConfigurationsFitted']}."]
        if result['additionalConfigurationsFitted']:
            lines+=['','| 모델 | 앞선 날짜 평균 IC | 후반 날짜 평균 IC |','|---|---:|---:|',
                f"| 기존 Ridge | {e1['scores']['selection']['ridgeAbsolute']['dateMeanIc']:.4f} | {e1['scores']['evaluation']['ridgeAbsolute']['dateMeanIc']:.4f} |",
                f"| 분기 실적 추가 Ridge | {result['scores']['selection']['dateMeanIc']:.4f} | {result['scores']['evaluation']['dateMeanIc']:.4f} |",'',
                f"앞선 구간 증분 개선: {result['earlierImproves']}. 후반 조건 충족: {result['laterEligible']}."]
        else:lines+=['',f"중단 이유: {result.get('blockReason','')}."]
        lines+=['','역사적 밸류에이션은 원주가·역사적 주식 수·기업행동 기준을 대조할 자료가 없어 실행하지 않았다.',
            '기존 가격 모델 승격: 없음. 재사용한 역사적 평가이며 새 실전 성능 검증이 아니다.']
        (folder/'E2-INCREMENT-RESULTS.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines),flush=True)
        return result
    if not all(result['sourceChecks'].values()):
        result.update(status='blocked_before_fitting',blockReason='Quarterly source controls did not pass')
        return finish()
    if e1['selected']!='ridgeAbsolute':raise ValueError('Unexpected earlier-selected E1 configuration')
    ds=prepare(root);panel,timelines=quarter_panel(root,ds,audit)
    comparison=ds['baseline']['stocks']['252']['comparison']
    origins=[f['origin'] for f in ds['baseline']['stocks']['252']['folds']]
    earlier=np.array([r['origin'] in comparison['selectionDates'] and r['targetDate']<comparison['evaluationStart'] for r in ds['meta']])
    later=np.array([r['origin'] in origins and r['origin']>=comparison['evaluationStart'] for r in ds['meta']])
    result['completeBaseCoverage']={k:float(np.isfinite(panel[mask,:3]).all(axis=1).mean()) for k,mask in (('earlier',earlier),('later',later))}
    if min(result['completeBaseCoverage'].values())<.5:
        result.update(status='blocked_before_fitting',blockReason='Fewer than half the rows have all three base quarter fields')
        return finish()
    X=np.column_stack([ds['X'],panel]);outcomes=[]
    for origin in origins:
        tick=time.monotonic();ids=np.array([i for i,r in enumerate(ds['meta']) if r['origin']==origin])
        predictions=fit_ridge(X,ds['Y'][:,0],ds['meta'],X[ids],origin)
        outcomes.extend(dict(ds['meta'][i],quarterlyRidge=float(v)) for i,v in zip(ids,predictions))
        atomic_json(folder/'e2-checkpoint.json',dict(result=result,outcomes=outcomes))
        print('E2 fit complete:',origin,'seconds',round(time.monotonic()-tick,1),flush=True)
    a=[r for r in outcomes if r['origin'] in comparison['selectionDates'] and r['targetDate']<comparison['evaluationStart']]
    b=[r for r in outcomes if r['origin']>=comparison['evaluationStart']]
    scores={k:evaluate(rows,'quarterlyRidge',{s:v['sector'] for s,v in ds['members'].items()}) for k,rows in (('selection',a),('evaluation',b))}
    uncertainty=date_uncertainty(scores['evaluation'],e1['scores']['evaluation']['ridgeAbsolute'])
    earlier_improves=scores['selection']['dateMeanIc']>e1['scores']['selection']['ridgeAbsolute']['dateMeanIc']
    later_checks=dict(positiveIc=scores['evaluation']['dateMeanIc']>0,
        improvesIc=scores['evaluation']['dateMeanIc']>e1['scores']['evaluation']['ridgeAbsolute']['dateMeanIc'],
        conservativeIcDifference=uncertainty['descriptiveDateBootstrap95'][0]>0,enoughDates=scores['evaluation']['dates']>=6)
    for cost in ('5','10','25'):
        delta=[r['costs'][cost]['selected']-e1['scores']['evaluation']['ridgeAbsolute']['byDate'][d]['costs'][cost]['selected'] for d,r in scores['evaluation']['byDate'].items()]
        later_checks['netImprovement'+cost]=float(np.mean(delta))>0
    result.update(status='completed',additionalConfigurationsFitted=1,scores=scores,uncertainty=uncertainty,
        earlierImproves=earlier_improves,laterChecks=later_checks,laterEligible=bool(earlier_improves and all(later_checks.values())),
        outcomeHash=hashlib.sha256(json.dumps(outcomes,sort_keys=True,allow_nan=False).encode()).hexdigest())
    return finish()

if __name__=='__main__':build()
