"""E0: frozen, chronological binary calibration comparisons on archived scores."""
import os
os.environ.setdefault('OMP_NUM_THREADS', '2')
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import math
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logit
from sklearn.metrics import roc_auc_score, average_precision_score
from build_forecasts import atomic_json

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT/'research/experiments/2026-09-13'
BASE_HASH = '287f4280b23def1489ad7062fbe35994f56f20ca7bd756bedb9bad85a374b08a'
SOURCE = 'independentReturn'
METHODS = ('raw', 'legacy', 'sigmoid8', 'sigmoid4')

def dated_weights(rows):
    sizes = Counter(r['origin'] for r in rows)
    return np.array([1/(len(sizes)*sizes[r['origin']]) for r in rows])

def calibration_prior(rows, origin, window):
    prior = [r for r in rows if r['origin'] < origin and r['targetDate'] < origin]
    dates = sorted({r['origin'] for r in prior})[-window:]
    return [r for r in prior if r['origin'] in dates]

def fit_monotone(prior):
    dates = sorted({r['origin'] for r in prior})
    labels = np.array([float(r['y'] < .98) for r in prior])
    status = dict(dates=len(dates), n=len(prior), fitted=False,
                  targetThrough=max((r['targetDate'] for r in prior), default=None))
    if len(dates) < 3 or min(sum(labels), len(labels)-sum(labels)) < 20:
        return None, status
    x = logit(np.clip([r[SOURCE+'Scores']['raw'][0] for r in prior], 1e-6, 1-1e-6))
    weights = dated_weights(prior)
    def objective(theta):
        a,b = theta
        z = a*x+b
        diff = weights*(expit(z)-labels)
        loss = float(np.dot(weights, np.logaddexp(0,z)-labels*z) + .005*a*a)
        gradient = np.array([np.dot(diff,x)+.01*a, sum(diff)])
        return loss, gradient
    opt = minimize(objective, [1.,0.], jac=True, method='L-BFGS-B',
                   bounds=[(1e-6,None),(None,None)], options={'ftol':1e-12,'gtol':1e-8,'maxiter':500})
    if not opt.success or not np.all(np.isfinite(opt.x)):
        raise RuntimeError('Monotone calibration optimizer failed: '+str(opt.message))
    a,b = (float(x) for x in opt.x)
    status.update(fitted=True, slope=a, intercept=b)
    return (a,b), status

def apply_monotone(raw, coefficients):
    a,b = coefficients
    return float(expit(a*logit(np.clip(raw,1e-6,1-1e-6))+b))

def predict_origin(all_rows, origin):
    test = sorted([r for r in all_rows if r['origin']==origin], key=lambda r:r['symbol'])
    prior = calibration_prior(all_rows,origin,8)
    base = float(np.dot(dated_weights(prior), [r['y']<.98 for r in prior])) if prior else None
    fits = {name:fit_monotone(calibration_prior(all_rows,origin,window))
            for name,window in (('sigmoid8',8),('sigmoid4',4))}
    predictions=[]
    for r in test:
        scores=r[SOURCE+'Scores'];raw=float(scores['raw'][0])
        row={k:r[k] for k in ('symbol','origin','targetDate','y')}
        row.update(raw=raw,legacy=float(scores['down']) if scores['calibrated'] else None,prior=base)
        for name,(coefficients,_) in fits.items():
            row[name]=apply_monotone(raw,coefficients) if coefficients else None
        predictions.append(row)
    return predictions, {k:s for k,(_,s) in fits.items()}

def metric(rows,name):
    if not rows:return dict(n=0,dates=0)
    by=defaultdict(list)
    for r in rows:by[r['origin']].append(r)
    date_metrics={}
    for day, rr in sorted(by.items()):
        y=np.array([r['y']<.98 for r in rr],dtype=int)
        p=np.clip([r[name] for r in rr],1e-12,1-1e-12)
        called=p>=.5;hits=int(sum(called & (y==1)))
        top=sorted(rr,key=lambda r:(-r[name],r['symbol']))[:math.ceil(.2*len(rr))]
        date_metrics[day]=dict(n=len(rr),brier=float(np.mean((p-y)**2)),
            logLoss=float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p))),
            auc=float(roc_auc_score(y,p)) if 0<sum(y)<len(y) else None,
            averagePrecision=float(average_precision_score(y,p)) if sum(y) else None,
            prevalence=float(y.mean()),called=int(sum(called)),down=int(sum(y)),hits=hits,
            top20Precision=sum(r['y']<.98 for r in top)/len(top))
    def mean(key):
        values=[v[key] for v in date_metrics.values() if v[key] is not None]
        return float(np.mean(values)) if values else None
    called=sum(v['called'] for v in date_metrics.values());down=sum(v['down'] for v in date_metrics.values())
    hits=sum(v['hits'] for v in date_metrics.values())
    bins=[]
    for lower,upper in zip((0,.2,.4,.6,.8),(.2,.4,.6,.8,1.)):
        rr=[r for r in rows if lower<=r[name] and (r[name]<upper or upper==1)]
        bins.append(dict(lower=lower,upper=upper,n=len(rr),
            predicted=float(np.mean([r[name] for r in rr])) if rr else None,
            observed=float(np.mean([r['y']<.98 for r in rr])) if rr else None))
    return dict(n=len(rows),dates=len(by),dateMeanBrier=mean('brier'),dateMeanLogLoss=mean('logLoss'),
        dateMeanAuc=mean('auc'),dateMeanAP=mean('averagePrecision'),
        top20DateMeanPrecision=mean('top20Precision'),dateMeanPrevalence=mean('prevalence'),
        predictedDown=called,actualDown=down,downRecall=hits/down if down else None,
        downPrecision=hits/called if called else None,alarmRate=called/len(rows),
        reliability=bins,byDate=date_metrics)

def checks(m,base,min_dates):
    return dict(enoughDates=m['dates']>=min_dates,
        brier=m.get('dateMeanBrier',math.inf)<base.get('dateMeanBrier',-math.inf),
        logLoss=m.get('dateMeanLogLoss',math.inf)<base.get('dateMeanLogLoss',-math.inf),
        discrimination=m.get('dateMeanAuc') is not None and m['dateMeanAuc']>.5)

def evaluate_group(group):
    all_rows=group['outcomes'];predictions=[];fits={}
    for origin in sorted({r['origin'] for r in all_rows}):
        p,f=predict_origin(all_rows,origin);predictions.extend(p);fits[origin]=f
    complete=[r for r in predictions if all(r.get(k) is not None for k in (*METHODS,'prior'))]
    c=group['comparison'];start=c['evaluationStart']
    earlier=[r for r in complete if r['origin'] in c['selectionDates'] and r['targetDate']<start]
    later=[r for r in complete if r['origin']>=start]
    selections={k:metric(earlier,k) for k in (*METHODS,'prior')}
    evaluations={k:metric(later,k) for k in (*METHODS,'prior')}
    prechecks={k:checks(selections[k],selections['prior'],3) for k in ('sigmoid8','sigmoid4')}
    eligible=[k for k,v in prechecks.items() if all(v.values())]
    selected=min(eligible,key=lambda k:(selections[k]['dateMeanBrier'],k)) if eligible else None
    laterchecks=checks(evaluations[selected],evaluations['prior'],6) if selected else None
    return dict(source=SOURCE,selection=selections,evaluation=evaluations,selectionChecks=prechecks,
        selected=selected,laterChecks=laterchecks,laterEligible=bool(laterchecks and all(laterchecks.values())),
        productionPromoted=False,originalPricePassed=c['passed'],
        sample=dict(total=len(predictions),complete=len(complete),earlier=len(earlier),later=len(later),
            laterExpected=sum(r['origin']>=start for r in predictions),evaluationStart=start),
        calibrations=fits,predictionHash=hashlib.sha256(json.dumps(predictions,sort_keys=True,allow_nan=False).encode()).hexdigest())

def build(root=ROOT):
    p=root/'research/environment.json'
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    if sha!=BASE_HASH:raise ValueError('Archived baseline changed; use the frozen experiment input')
    data=json.loads(p.read_text())
    result=dict(experiment='stock-validation-e0-v1',generatedAt=datetime.now(timezone.utc).isoformat(),
        inputHash=sha,sourceModel=data['model'],protocol='PROTOCOL.md',newConfigurations=6,
        interpretation='Revisited historical development evaluation. No production or prospective claim.',
        horizons={h:evaluate_group(data['stocks'][h]) for h in ('126','252')})
    folder=root/'research/experiments/2026-09-13';folder.mkdir(parents=True,exist_ok=True)
    atomic_json(folder/'e0-calibration.json',result)
    lines=['# E0: 확률 보정 실험 결과','',
        '같은 원점수·종목·날짜에서 비교했다. 기존 후반 구간의 재분석이며 운영 모델 승격은 없다.','',
        '| 기간 | 방법 | 날짜 평균 Brier ↓ | 날짜 평균 AUC ↑ | 하락 재현율 (p≥0.5) | 경보 수 |',
        '|---|---|---:|---:|---:|---:|']
    labels={'raw':'보정 전','legacy':'기존 다항 보정','sigmoid8':'단조 보정 8개 날짜','sigmoid4':'단조 보정 4개 날짜','prior':'과거 하락 빈도'}
    for h,g in result['horizons'].items():
        for name,m in g['evaluation'].items():
            lines.append(f"| {int(h)//21}개월 | {labels[name]} | {m['dateMeanBrier']:.4f} | {m['dateMeanAuc']:.4f} | {100*m['downRecall']:.2f}% | {m['predictedDown']} |")
    for h,g in result['horizons'].items():
        lines.extend(['',f"{int(h)//21}개월: 앞선 구간 선정={g['selected'] or '적격 후보 없음'}, 후반 조건 충족={g['laterEligible']}. 평가 표본 {g['sample']['later']}/{g['sample']['laterExpected']}건.",''])
    lines.extend(['','AUC 0.5는 무작위 구별 수준이다. Brier는 확률 오차이며 작을수록 좋다.',
        '확률 기준선도 과거에 확정된 결과만 사용한다. 보정 실패 시에도 독립된 E1 순위 가설은 계속 검증한다.'])
    (folder/'E0-RESULTS.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines),flush=True)
    return result

if __name__=='__main__':build()
