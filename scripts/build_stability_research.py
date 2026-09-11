"""Predeclared robust candidates; chronological selection and later evaluation.

This research never changes the production forecast or its promotion gate.
Historical periods have been explored before; later evaluation is held out
from this candidate selection, not a substitute for prospective performance.
"""
import json
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from build_learned_forecasts import load_frames,examples,FEATURES,PARAMS
from build_forecasts import atomic_json

ROOT=Path(__file__).resolve().parents[1]
CANDIDATES=('noChange','trend','original','relativeMAE','halfBlend')

def stats(rows,name):
    if not rows:return dict(n=0,dates=0,mape=None,dateMeanMape=None,p90=None,within10=None,direction=None)
    actual=np.array([r['actual'] for r in rows]);pred=np.array([r[name] for r in rows])
    error=np.abs(pred-actual)/actual
    dates=sorted({r['origin'] for r in rows})
    bydate={d:float(np.mean([error[i] for i,r in enumerate(rows) if r['origin']==d])) for d in dates}
    direction=lambda a:np.where(a>1.02,1,np.where(a<.98,-1,0))
    return dict(n=len(rows),dates=len(dates),mape=float(error.mean()),dateMeanMape=float(np.mean(list(bydate.values()))),
                p90=float(np.quantile(error,.9)),within10=float(np.mean(error<=.1)),
                direction=float(np.mean(direction(actual)==direction(pred))),byDate=bydate,
                worstDateMape=max(bydate.values()),alwaysUp=float(np.mean(actual>1.02)))

def compare(rows):
    dates=sorted({r['origin'] for r in rows})
    if len(dates)<4:return dict(status='insufficient',liveForecastChanged=False)
    split=max(2,len(dates)//2)
    # Calendar-only boundary: leave enough strictly matured selection origins.
    # Never move the boundary in response to candidate accuracy.
    while split<len(dates)-1:
        selection=[r for r in rows if r['origin'] in dates[:split] and r['targetDate']<dates[split]]
        if len({r['origin'] for r in selection})>=2:break
        split+=1
    evaluation_start=dates[split]
    selection=[r for r in rows if r['origin'] in dates[:split] and r['targetDate']<evaluation_start]
    test=[r for r in rows if r['origin'] in dates[split:]]
    if len({r['origin'] for r in selection})<2:return dict(status='insufficient',liveForecastChanged=False)
    earlier={name:stats(selection,name) for name in CANDIDATES}
    # Fixed before this experiment: date-balanced MAPE plus tail-error penalty.
    chosen=min(CANDIDATES,key=lambda name:earlier[name]['dateMeanMape']+.25*earlier[name]['p90'])
    later={name:stats(test,name) for name in CANDIDATES};m=later[chosen]
    wins=sum(m['byDate'][d]<min(later[b]['byDate'][d] for b in ('noChange','trend')) for d in m['byDate'])
    checks=dict(enoughDates=m['dates']>=4,
                average=m['dateMeanMape']<.98*min(later[b]['dateMeanMape'] for b in ('noChange','trend','original')),
                tail=m['p90']<=min(later[b]['p90'] for b in ('noChange','trend')),
                consistency=wins/m['dates']>=.60,direction=m['direction']>=m['alwaysUp'])
    return dict(status='research',chosen=chosen,selection=earlier,evaluation=later,checks=checks,
                selectionDates=sorted({r['origin'] for r in selection}),evaluationDates=dates[split:],
                selectionTargetThrough=max(r['targetDate'] for r in selection),evaluationStart=evaluation_start,
                dateWinRate=wins/m['dates'],passed=all(checks.values()),liveForecastChanged=False,
                note='Candidate chosen using earlier outcomes only. Later periods were previously explored in other research; this is not prospective validation.')

def fit_relative(train):
    target=np.exp(train.y.to_numpy())
    # |predicted gross return - actual gross return| / actual gross return
    # is exactly the relative error of the future price. No outcome clipping.
    weights=1/target
    if not np.isfinite(weights).all():raise ValueError('Invalid relative-error weights')
    return HistGradientBoostingRegressor(**PARAMS,loss='absolute_error').fit(train[FEATURES],target,sample_weight=weights)

def build(root=ROOT):
    latest=json.loads((root/'ml/latest.json').read_text())
    frames,hashes=load_frames(root,latest['generatedAt'])
    if not frames:raise ValueError('Full histories required for stability research')
    if hashes!=latest['historyHashes']:raise ValueError('Input histories differ from the production comparison')
    calendar=list(frames['SPY'].index);allowed=set(calendar[::21])
    out=dict(schemaVersion=1,model='relative-error-stability-v1',generatedAt=datetime.now(timezone.utc).isoformat(),
             sourceGeneratedAt=latest['generatedAt'],sourceModel=latest['model'],horizons={},
             method='Fixed weighted absolute-error HGB and 50% no-change blend; date-mean MAPE + 0.25*p90 selection objective; same-observation comparisons.',
             limitations=['Current-universe survivorship bias remains.','Only price/volume patterns; no point-in-time fundamental or credit data.',
                          'Small date samples and correlated stocks; no significance or live-performance claim.','No automatic forecast promotion.'])
    for h in (21,84,252):
        source=json.loads((root/f'ml/validation/{h}.json').read_text())
        assert source['generatedAt']==latest['generatedAt']
        data=examples(frames,h);rows=[];folds=[]
        for meta in source['folds']:
            origin=meta['origin'];cut=meta['trainCutoff']
            train=data[(data.targetDate<cut)&(data.origin<cut)&data.origin.isin(allowed)]
            original=[r for r in source['outcomes'] if r['origin']==origin]
            if not original:continue
            keys=pd.DataFrame(original)[['symbol','origin']]
            test=keys.merge(data.reset_index(drop=True),on=['symbol','origin'],how='left',validate='one_to_one')
            if test[FEATURES].isna().any(axis=None):raise ValueError('Unmatched comparison observations')
            model=fit_relative(train);prediction=model.predict(test[FEATURES])
            if not (np.isfinite(prediction)&(prediction>0)).all():raise ValueError('Invalid robust predictions')
            for i,r in enumerate(original):
                assert abs(float(test.iloc[i].y)-r['y'])<1e-10
                rows.append(dict(symbol=r['symbol'],origin=origin,targetDate=r['targetDate'],actual=float(np.exp(r['y'])),
                                 noChange=1.,trend=float(np.exp(r['trend'])),original=float(np.exp(r['pred'])),
                                 relativeMAE=float(prediction[i]),halfBlend=float(.5+.5*prediction[i])))
            folds.append(dict(origin=origin,trainTargetThrough=str(train.targetDate.max()),trainCutoff=cut,trainRows=len(train)))
        result=compare(rows);result['folds']=folds
        out['horizons'][str(h)]=result
        atomic_json(root/f'ml/stability/{h}.json',dict(model=out['model'],sourceGeneratedAt=latest['generatedAt'],rows=rows))
        print('Stability',h,result.get('chosen'),result.get('checks'),flush=True)
    atomic_json(root/'ml/stability.json',out)
    return out

if __name__=='__main__':build()
