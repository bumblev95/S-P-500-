"""Frozen, walk-forward forecast correction using completed out-of-sample errors.

Two candidates, no search: half median log-bias correction and a conservative
regime-aware blend of AI/no-change/trend. These are learned forecast adapters,
not newly trained foundation models. Historical evaluation is exploratory;
only the existing prospective registry may promote a candidate.
"""
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from build_forecasts import atomic_json

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'completed-error-adapter-v1'
VARIANTS = ('biasCorrected', 'regimeBlend')
BASES = ('original', 'noChange', 'trend')
MIN_DATES = 4
MAX_DATES = 12
SELECTION_RULE = 'joint-price-direction-v1'

def direction(log_returns):
    # Compare in the stored log domain so exact +/-2% endpoints stay neutral.
    x = np.asarray(log_returns)
    return np.where(x > math.log(1.02), 1, np.where(x < math.log(.98), -1, 0))

def quantile(values, weights, q):
    pairs = sorted(zip(values, weights))
    threshold = q * sum(weights)
    total = 0
    for value, weight in pairs:
        total += weight
        if total >= threshold:
            return float(value)
    return float(pairs[-1][0])

def weights(rows):
    counts = Counter(r['origin'] for r in rows)
    return np.array([1 / counts[r['origin']] for r in rows])

def regime(r):
    if not all(isinstance(r.get(k), (int, float)) and math.isfinite(r[k]) for k in ('ma200','vol84')):
        return 'unknown'
    return ('above200' if r['ma200'] >= 0 else 'below200') + ('HighVol' if r['vol84'] >= .4 else 'LowVol')

def matured(rows, origin):
    # Entire date blocks must have matured; never partially select a date's stocks.
    by_date = {}
    for r in rows:
        by_date.setdefault(r['origin'], []).append(r)
    dates = [d for d, block in sorted(by_date.items())
             if d < origin and max(r['targetDate'] for r in block) < origin]
    result = [r for d in dates for r in by_date[d]]
    # Retain disjoint windows even if an upstream producer changes its sampling.
    keep = []; through = ''
    for d in dates:
        # Return windows are (origin, target]; sharing a boundary close is valid.
        if d < through:
            continue
        keep.append(d)
        through = max(r['targetDate'] for r in by_date[d])
    keep = set(keep[-MAX_DATES:])
    return [r for r in result if r['origin'] in keep]

def fit(rows, origin):
    prior = matured(rows, origin)
    if len({r['origin'] for r in prior}) < MIN_DATES or len(prior) < 60:
        return None
    w = weights(prior)
    residual = np.array([r['y'] - r['original'] for r in prior])
    # Fixed 50% shrinkage reduces sensitivity to the small number of market dates.
    bias = .5 * quantile(residual, w, .5)
    actual = np.expm1([r['y'] for r in prior])
    loss = []
    for name in BASES:
        error = abs(np.expm1([r[name] for r in prior]) - actual)
        loss.append(float(np.average(error, weights=w)) + .25 * quantile(error, w, .9))
    inverse = 1 / np.maximum(loss, .005)
    # Half equal-weight prior, half inverse-error allocation. No winner-take-all.
    mix = .5 / len(BASES) + .5 * inverse / inverse.sum()
    blended = np.array([[r[b] for b in BASES] for r in prior]) @ mix
    mix_bias = .5 * quantile(np.array([r['y'] for r in prior]) - blended, w, .5)
    return dict(bias=float(bias), blendBias=float(mix_bias), weights=dict(zip(BASES, mix.tolist())),
                dates=len({r['origin'] for r in prior}), n=len(prior),
                targetThrough=max(r['targetDate'] for r in prior))

def predict(row, pooled, local=None):
    p = local or pooled
    return dict(biasCorrected=row['original'] + pooled['bias'],
                regimeBlend=sum(row[b] * p['weights'][b] for b in BASES) + p['blendBias'])

def band(prior, origin, variant):
    prior = matured([r for r in prior if variant in r], origin)
    if len({r['origin'] for r in prior}) < 3 or len(prior) < 60:
        return None
    residual = [r['y'] - r[variant] for r in prior]; w = weights(prior)
    return dict(lowOffset=min(0., quantile(residual, w, .1)),
                highOffset=max(0., quantile(residual, w, .9)),
                dates=len({r['origin'] for r in prior}), n=len(prior),
                targetThrough=max(r['targetDate'] for r in prior))

def stats(rows, name):
    rows = [r for r in rows if name in r]
    if not rows:
        return dict(n=0, dates=0, mae=None, mape=None, p90=None, directionAccuracy=None)
    w = weights(rows)
    try:
        with np.errstate(over='raise', invalid='raise', divide='raise'):
            actual = np.expm1([r['y'] for r in rows]); pred = np.expm1([r[name] for r in rows])
            error = abs(pred - actual); price_error = error / np.exp([r['y'] for r in rows])
    except FloatingPointError as problem:
        raise ValueError('Nonfinite comparison metric; reject the entire cohort') from problem
    if not np.isfinite(error).all() or not np.isfinite(price_error).all():
        raise ValueError('Nonfinite comparison metric; reject the entire cohort')
    truth = direction([r['y'] for r in rows]); predicted = direction([r[name] for r in rows])
    by = {d:float(np.mean([error[i] for i,r in enumerate(rows) if r['origin']==d])) for d in sorted({r['origin'] for r in rows})}
    out = dict(n=len(rows), dates=len(by), mae=float(np.average(error,weights=w)),
               mape=float(np.average(price_error,weights=w)), p90=quantile(error,w,.9), p90Mape=quantile(price_error,w,.9),
               bias=float(np.average(pred-actual,weights=w)),
               directionAccuracy=float(np.average(predicted==truth,weights=w)),
               alwaysUpAccuracy=float(np.average(truth==1,weights=w)), byDate=by)
    conditional = lambda mask, given: float(w[mask & given].sum()/w[given].sum()) if w[given].sum() else None
    recalls = [conditional(predicted==c, truth==c) for c in (-1,0,1)]
    out.update(downRecall=recalls[0], upRecall=recalls[2],
               balancedAccuracy=float(np.mean([v for v in recalls if v is not None])),
               downPrecision=conditional(truth==-1, predicted==-1),
               downFalsePositiveRate=conditional(predicted==-1, truth!=-1),
               downPrevalence=float(np.average(truth==-1, weights=w)),
               actualDownCount=int((truth==-1).sum()), downWarnings=int((predicted==-1).sum()))
    interval_rows = [r for r in rows if r.get('bands',{}).get(name)]
    if interval_rows:
        iw = weights(interval_rows)
        out['rangeCoverage'] = float(np.average([r[name]+r['bands'][name]['lowOffset']<=r['y']<=r[name]+r['bands'][name]['highOffset'] for r in interval_rows], weights=iw))
        out['rangeDates'] = len({r['origin'] for r in interval_rows})
    return out

def validate_comparison_rows(rows):
    """Reject an incomplete candidate table, never improve a score by dropping rows."""
    keys = set(); through = ''
    for origin in sorted({r['origin'] for r in rows}):
        if datetime.strptime(origin, '%Y-%m-%d').date().isoformat() != origin:
            raise ValueError('Invalid origin date')
        block = [r for r in rows if r['origin'] == origin]
        if origin < through:
            raise ValueError('Overlapping comparison date blocks')
        for r in block:
            key = (r['symbol'], origin)
            if key in keys:
                raise ValueError('Duplicate comparison row')
            keys.add(key)
            target = r['targetDate']
            if datetime.strptime(target, '%Y-%m-%d').date().isoformat() != target or target <= origin:
                raise ValueError('Invalid comparison target')
            if 'correctionTargetThrough' in r and not r['correctionTargetThrough'] < origin:
                raise ValueError('Adapter used unmatured outcomes')
            for name in ('y', *BASES, *VARIANTS):
                value = r.get(name)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError('Missing/nonfinite paired prediction: '+name)
                try:
                    ratio = math.exp(value)
                except OverflowError as error:
                    raise ValueError('Invalid predicted/realized price ratio') from error
                if ratio <= 0 or not math.isfinite(ratio):
                    raise ValueError('Invalid predicted/realized price ratio')
        through = max(r['targetDate'] for r in block)

def joint_checks(new, evaluation):
    """Fixed feasibility guards precede the original error objective; no tradeoffs."""
    old = evaluation['original']; tol = 1e-12
    present = lambda value: value is not None and math.isfinite(value)
    recall = lambda field: (old[field] is None or
                            present(new[field]) and new[field]+tol >= old[field])
    no_down = new['actualDownCount'] == 0 and new['downWarnings'] == 0
    return dict(
        average=new['mae'] < .98*min(evaluation[b]['mae'] for b in BASES),
        mape=new['mape'] <= min(evaluation[b]['mape'] for b in BASES)+tol,
        tail=new['p90'] <= min(evaluation[b]['p90'] for b in BASES)+tol,
        tailMape=new['p90Mape'] <= min(evaluation[b]['p90Mape'] for b in BASES)+tol,
        direction=new['directionAccuracy']+tol >= max(old['directionAccuracy'], new['alwaysUpAccuracy']),
        balancedDirection=new['balancedAccuracy']+tol >= old['balancedAccuracy'],
        downRecall=recall('downRecall') and (new['actualDownCount'] < 20 or
                                            present(new['downRecall']) and new['downRecall'] >= .10),
        upRecall=recall('upRecall'),
        downPrecision=no_down or present(new['downPrecision']) and
                      new['downPrecision']+tol >= max(old['downPrecision'] or 0., new['downPrevalence']),
        falseDown=no_down or present(new['downFalsePositiveRate']) and
                  (old['downFalsePositiveRate'] is None or new['downFalsePositiveRate'] <= old['downFalsePositiveRate']+tol))

def compare(rows):
    """Separate a diagnostic winner, a joint-qualified candidate and live eligibility.

    Selection uses only whole earlier matured blocks. Later outcomes may reject
    that choice but cannot choose a replacement. Revisited/PIT-incomplete evidence
    is never production eligible, including when all statistical checks pass.
    """
    validate_comparison_rows(rows)
    safety = dict(selectionRule=SELECTION_RULE, selectedCandidate=None, selectionEligible=False,
                  chosenScope='diagnostic-only', productionEligible=False, promotionCandidate=False,
                  pitComplete=False, untouchedProspectiveEvidence=False, automaticPromotion=False,
                  liveForecastChanged=False, usedForTrading=False, retainedModel='original')
    dates = sorted({r['origin'] for r in rows})
    if len(dates) < 4:
        return dict(safety,status='insufficient',chosen=None,diagnosticChoice=None,passed=False,
                    reason='보정 후 독립 검증 시점 부족',evaluation={},checks={})
    split = max(2,len(dates)//2)
    start = dates[split]
    selection = matured([r for r in rows if r['origin']<start],start)
    if len({r['origin'] for r in selection}) < 2:
        return dict(safety,status='insufficient',chosen=None,diagnosticChoice=None,passed=False,
                    reason='모델 선택 이전 완료 시점 부족',evaluation={},checks={})
    selection_evaluation = {v:stats(selection,v) for v in (*BASES,*VARIANTS)}
    objective = lambda v: selection_evaluation[v]['mae']+.25*selection_evaluation[v]['p90']
    diagnostic = min(VARIANTS,key=objective)
    selection_checks = {v:{k:bool(x) for k,x in joint_checks(selection_evaluation[v],selection_evaluation).items()} for v in VARIANTS}
    eligible = [v for v in VARIANTS if all(selection_checks[v].values())]
    selected = min(eligible,key=objective) if eligible else None
    # Keep legacy `chosen` readable by existing display-only consumers; explicitly
    # mark it diagnostic-only when no candidate clears the joint selection screen.
    chosen = selected or diagnostic
    later = [r for r in rows if r['origin']>=start]
    evaluation = {v:stats(later,v) for v in (*BASES,*VARIANTS)}
    new = evaluation[chosen]; old = evaluation['original']
    wins = np.mean([new['byDate'][d] < min(evaluation[b]['byDate'][d] for b in BASES) for d in new['byDate']])
    checks = dict(selectionEligible=selected is not None, enoughDates=new['dates']>=4,
                  **joint_checks(new,evaluation), consistency=bool(wins>=.6))
    checks = {k:bool(v) for k,v in checks.items()}
    return dict(safety,status='research',chosen=chosen,diagnosticChoice=diagnostic,
                selectedCandidate=selected,selectionEligible=selected is not None,
                chosenScope='joint-qualified-retrospective-candidate' if selected else 'diagnostic-only',
                passed=all(checks.values()),checks=checks,selectionChecks=selection_checks,
                selectionEvaluation=selection_evaluation,
                reason=None if selected else '평균 가격 오차와 방향성 공동 선택 조건 미충족; 진단 후보만 기록',
                selectionDates=sorted({r['origin'] for r in selection}),selectionTargetThrough=max(r['targetDate'] for r in selection),
                evaluationStart=start,evaluation=evaluation,dateWinRate=float(wins),
                improvementVsOriginal=1-new['mae']/old['mae'] if old['mae'] else None,
                evidenceClass='quarantined-retrospective-diagnostic')

def normalize(source):
    result=[]; seen=set()
    for q in source.get('outcomes',[]):
        k=(q['symbol'],q['origin'])
        if k in seen: raise ValueError('Duplicate out-of-sample observation')
        seen.add(k)
        if q['targetDate']<=q['origin'] or not all(isinstance(q[n], (int,float)) and not isinstance(q[n],bool) and math.isfinite(q[n]) for n in ('y','pred','trend')):
            raise ValueError('Invalid realized target')
        result.append(dict(q,original=q['pred'],noChange=0.))
    folds={}
    for f in source['folds']:
        if f['origin'] in folds:
            raise ValueError('Duplicate source fold')
        folds[f['origin']] = f
    for r in result:
        if r['origin'] not in folds:
            raise ValueError('Missing source fold')
        f=folds[r['origin']]
        if not f['trainTargetThrough']<r['origin'] or not f['calibrationTargetThrough']<r['origin']:
            raise ValueError('Source model used future outcomes')
        if source.get('generatedAt') and r['targetDate'] > source['generatedAt'][:10]:
            raise ValueError('Source outcome has not matured')
    return result

def forecast_row(entry, stock, horizon):
    p=entry['predictions'][str(horizon)]['forecast']; anchor=p['anchor']
    inputs=stock.get('inputs',{}) if stock.get('asOf')==entry['asOf'] else {}
    valid=lambda v:isinstance(v,(int,float)) and math.isfinite(v)
    rs=[inputs.get('return1m'),inputs.get('return3m'),inputs.get('return6m')]
    if not all(valid(r) and r>-1 for r in rs): return None
    momentum=.5*math.log1p(rs[0])/21+.3*math.log1p(rs[1])/63+.2*math.log1p(rs[2])/126
    trend=float(np.clip(.35*momentum,-.6/252,.6/252)*63*(1-math.exp(-horizon/63)))
    ma=inputs.get('ma200')
    return dict(origin=entry['asOf'],original=math.log(p['base']/anchor),noChange=0.,trend=trend,
                ma200=anchor/ma-1 if valid(ma) and ma>0 else None,vol84=inputs.get('volatility4m'))

def build(root=ROOT, now=None):
    now=now or datetime.now(timezone.utc).isoformat(timespec='seconds')
    latest=json.loads((root/'ml/latest.json').read_text()); stocks=json.loads((root/'forecasts/latest.json').read_text()).get('stocks',{})
    model_id=MODEL+':'+latest['model']
    out=dict(schemaVersion=1,model=model_id,sourceModel=latest['model'],generatedAt=now,sourceGeneratedAt=latest['generatedAt'],
             horizons={},stocks={},method='Two fixed forecast adapters; date-equal completed out-of-sample errors; purged walk-forward; no parameter search.',
             limitations=['기존 과거 기간을 다시 분석한 탐색 연구이며 새로운 실전 성적이 아닙니다.',
                          '기업별 장기 이동평균·변동성 구분이며 거시경제 전체를 설명하지 않습니다.',
                          '500개 종목도 같은 날짜면 하나의 시장 시점입니다. 생존편향이 남습니다.',
                          '기본 모델 교체는 별도 실제 발표 성적표의 승격 조건을 따릅니다.'],
             sources=['https://scikit-learn.org/stable/modules/ensemble.html#gradient-boosting',
                      'https://otexts.com/fpp3/tscv.html'])
    for h in (126,252):
        source=json.loads((root/f'ml/validation/{h}.json').read_text())
        if source['model']!=latest['model'] or source['generatedAt']!=latest['generatedAt']:
            raise ValueError('Mismatched source validation snapshot')
        all_rows=normalize(source); evaluated=[]; folds=[]
        origins=sorted({r['origin'] for r in all_rows}); through=''
        for origin in origins:
            block=[r for r in all_rows if r['origin']==origin]
            if origin<through: continue
            through=max(r['targetDate'] for r in block)
            pooled=fit(all_rows,origin)
            if not pooled: continue
            locals_={g:fit([r for r in all_rows if regime(r)==g],origin) for g in {regime(r) for r in block}}
            bands={v:band(evaluated,origin,v) for v in VARIANTS}
            for r in block:
                evaluated.append(dict(r,**predict(r,pooled,locals_.get(regime(r))),bands=bands,
                                      correctionTargetThrough=pooled['targetThrough']))
            folds.append(dict(origin=origin,**pooled))
        comparison=compare(evaluated)
        regimes={g:{v:stats([r for r in evaluated if regime(r)==g],v) for v in (*BASES,*VARIANTS)} for g in sorted({regime(r) for r in evaluated})}
        baseline={v:stats(all_rows,v) for v in BASES}
        out['horizons'][str(h)]=dict(comparison=comparison,allEvaluation={v:stats(evaluated,v) for v in (*BASES,*VARIANTS)},
                                   sourceDiagnostics=baseline,regimes=regimes,folds=folds,sourceDates=len(origins),
                                   correctionDates=len(folds),sourceN=len(all_rows))
        live_cache={}
        for sym,entry in latest['stocks'].items():
            if str(h) not in entry.get('predictions',{}): continue
            r=forecast_row(entry,stocks.get(sym,{}),h)
            if r is None:continue
            origin=r['origin']
            if origin not in live_cache:
                pooled=fit(all_rows,origin)
                live_cache[origin]=(pooled,{g:fit([q for q in all_rows if regime(q)==g],origin) for g in {regime(q) for q in all_rows}} if pooled else {},{v:band(evaluated,origin,v) for v in VARIANTS})
            pooled,locals_,bands=live_cache[origin]
            if not pooled:continue
            point=predict(r,pooled,locals_.get(regime(r))); anchor=entry['predictions'][str(h)]['forecast']['anchor']
            own=[q for q in evaluated if q['symbol']==sym]
            predictions={}
            for v,p in point.items():
                b=bands[v];validation=stats(own,v);base_stats=stats(own,'noChange')
                validation.update(noChangeMae=base_stats['mae'],noChangeMape=base_stats['mape'],p90Error=validation.get('p90Mape'))
                predictions[v]=dict(model=model_id+':'+v,base=anchor*math.exp(p),
                                    low=anchor*math.exp(p+b['lowOffset']) if b else None,
                                    high=anchor*math.exp(p+b['highOffset']) if b else None,
                                    validation=validation,calibration=b)
            out['stocks'].setdefault(sym,{})[str(h)]=dict(asOf=origin,anchor=anchor,variants=predictions,
                correction=pooled,regime=regime(r),localCorrection=locals_.get(regime(r)),source='Yahoo EOD',eligible=False)
        atomic_json(root/f'ml/adaptive/{h}.json',dict(model=model_id,sourceGeneratedAt=latest['generatedAt'],rows=evaluated))
        print('Adaptive',h,comparison.get('chosen'),comparison.get('checks'),comparison.get('improvementVsOriginal'),flush=True)
    atomic_json(root/'ml/adaptive.json',out)
    atomic_json(root/'ml/adaptive-summary.json',{k:v for k,v in out.items() if k!='stocks'})
    return out

if __name__=='__main__':build()
