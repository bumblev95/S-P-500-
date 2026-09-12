"""Chronological net-payoff selection, daily-history transfer and exit ablation."""
import os
os.environ.setdefault('OMP_NUM_THREADS','2');os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
import json,hashlib,subprocess,warnings,bisect
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
import sklearn,joblib
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'simulation/selector-research';DAY=86400000

def timestamp(s):return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()*1000)
def daily_features(prices,i):
    if i<120:return None
    a=np.array(prices[i-120:i+1]);ret=np.diff(np.log(a))
    return [a[-1]/a[-1-n]-1 for n in [7,14,30,90]]+[float(np.std(ret[-30:])),float(a[-1]/np.max(a)-1),float(a[-1]/np.mean(a[-60:])-1)]

def closed_before(rows,start,end,boundary):
    return [r for r in rows if r.get('labelEnd',float('inf'))<boundary-DAY and start<=r['at']<end and 'netR' in r]

def build():
    plan=json.loads((OUT/'plan.json').read_text());data=json.loads(Path('/tmp/selector-samples.json').read_text());rows=data['rows']
    daily=json.loads((OUT/'btc-daily.json').read_text());prices=[r['price'] for r in daily['rows']]
    ds=[]
    for i in range(120,len(prices)-14):
        x=daily_features(prices,i);at=timestamp(daily['rows'][i]['date'])+2*DAY
        ds.append(dict(at=at,labelEnd=timestamp(daily['rows'][i+14]['date'])+2*DAY,x=x,y=int(prices[i+14]>prices[i])))
    # Daily inputs from actually completed futures days, never from future daily closes.
    raw=json.loads(Path('/tmp/paper-long-cache/market.json').read_text())['crypto']['BTC']['frames']['15m'];groups={}
    for r in raw:groups.setdefault(r['t']//DAY,[]).append(r)
    bd=[]
    for day,g in sorted(groups.items()):
        if len(g)==96 and g[0]['t']==day*DAY and g[-1]['end']==(day+1)*DAY-1:bd.append((day,g[-1]['close']))
    bp=[p for _,p in bd];bx={}
    for i in range(120,len(bd)):
        if bd[i][0]-bd[i-120][0]==120:bx[(bd[i][0]+2)*DAY]=daily_features(bp,i)
    bt=sorted(bx)
    for r in rows:
        j=bisect.bisect_right(bt,r['at'])-1
        r['dailyX']=bx[bt[j]] if j>=0 and r['at']-bt[j]<2*DAY else None
    # Build out-of-time auxiliary scores separately for each historical window.
    context={};contextAudit=[]
    for window in plan['trainingWindows']:
      for year in range(2020,2027):
        boundary=timestamp(f'{year}-01-01');start=timestamp('2014-01-01') if window=='all' else timestamp(f'{year-int(window[0])}-01-01')
        train=[r for r in ds if start<=r['at'] and r['labelEnd']<boundary-DAY]
        m=make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=300,random_state=42));m.fit([r['x'] for r in train],[r['y'] for r in train])
        selected=[r for r in rows if datetime.fromtimestamp(r['at']/1000,timezone.utc).year==year and r['dailyX'] is not None]
        scores=m.predict_proba([r['dailyX'] for r in selected])[:,1] if selected else []
        for r,p in zip(selected,scores):context[(window,r['symbol'],r['at'])]=float(p)
        contextAudit.append(dict(window=window,year=year,count=len(train),firstAt=min(r['at'] for r in train),lastLabelEnd=max(r['labelEnd'] for r in train),predictionStart=boundary))
        joblib.dump(m,OUT/f'context-{window}-{year}.joblib',compress=3)
    worker=subprocess.Popen(['node','scripts/selector_worker.cjs'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
    def evaluate(start,end,scores=None,**kw):
        worker.stdin.write(json.dumps(dict(start=start,end=end,scores=scores,**kw))+'\n');worker.stdin.flush();s=worker.stdout.readline()
        if not s:raise RuntimeError('Evaluation worker exited')
        r=json.loads(s)
        if 'error' in r:raise RuntimeError(r['error'])
        return r
    report=dict(version=plan['version'],generatedAt=datetime.now(timezone.utc).isoformat(),deployed=False,status='과거 탐색 실험 · 미래 검증 대기',dailyCoverage={k:v for k,v in daily.items() if k!='rows'},futuresCoverage=json.loads(Path('/tmp/paper-long-cache/manifest.json').read_text())['coverage'],dailyCount=len(daily['rows']),candidateCount=len(rows),trainingLabelCount=sum('netR'in r for r in rows),features=data['features']+['directional_daily_context','daily_context_missing'],contextAudit=contextAudit,periods=[],sklearnVersion=sklearn.__version__,plan='plan.json',notes=plan['limitations'])
    definitions=[(family,w,True) for family in ['boost','mlp'] for w in plan['trainingWindows']]+[('boost','all',False)]
    for year in plan['evaluationYears']:
        start=timestamp(f'{year}-01-01');end=min(timestamp(f'{year+1}-01-01')-1,timestamp('2026-09-01')-1);valStart=timestamp(f'{year-1}-07-01');valEnd=start-1
        period=dict(year=year,start=start,end=end,validationStart=valStart,validationEnd=valEnd,results=[],validation=[],training=[])
        baseline=evaluate(start,end,stress=True);baseline['method']='baseline';period['results'].append(baseline)
        valBase=evaluate(valStart,valEnd,compact=True);period['validationBaseline']=valBase
        candidates={}
        for family,window,useContext in definitions:
            key=family+'-'+window+('' if useContext else '-no-context')
            trainStart=timestamp('2020-01-01') if window=='all' else timestamp(f'{year-int(window[0])}-01-01')
            training=closed_before(rows,trainStart,valStart,valStart)
            def xx(rs):
                a=[]
                for r in rs:
                    p=context.get((window,r['symbol'],r['at'])) if useContext else None
                    a.append(r['x']+([(2*p-1)*r['x'][0] if p is not None else 0, int(p is None)] if useContext else []))
                return np.array(a)
            if family=='boost':model=HistGradientBoostingRegressor(random_state=42,**plan['models']['boost'])
            else:
                cfg={**plan['models']['mlp']};cfg['hidden_layer_sizes']=tuple(cfg['hidden_layer_sizes']);model=make_pipeline(StandardScaler(),MLPRegressor(**cfg))
            with warnings.catch_warnings(record=True) as caught:
                model.fit(xx(training),np.clip([r['netR'] for r in training],-3,6))
            selected=[r for r in rows if valStart<=r['at']<=end]
            pred=model.predict(xx(selected));scores=[[r['symbol'],r['at'],float(p)] for r,p in zip(selected,pred)]
            validation=evaluate(valStart,valEnd,scores,compact=True);validation.update(method=key,eligible=validation['trades']>=20,selectionScore=validation['return']-validation['maxDrawdown']);period['validation'].append(validation)
            result=evaluate(start,end,scores,stress=True);result.update(method=key,acceptedSignals=int(sum(p>=.10 for r,p in zip(selected,pred) if r['at']>=start)),totalSignals=sum(r['at']>=start for r in selected));period['results'].append(result)
            audit=dict(method=key,trainCount=len(training),firstAt=min(r['at'] for r in training),lastLabelEnd=max(r['labelEnd'] for r in training),validationStart=valStart,warnings=[str(w.message) for w in caught]);period['training'].append(audit)
            assert audit['lastLabelEnd']<valStart-DAY
            candidates[key]=scores
            joblib.dump(model,OUT/f'model-{year}-{key}.joblib',compress=3)
            (OUT/f'scores-{year}-{key}.json').write_text(json.dumps(scores,separators=(',',':')))
            print(json.dumps(dict(year=year,method=key,train=len(training),validation=validation['return'],test=result['return'],dd=result['maxDrawdown'],trades=result['trades'])),flush=True)
        eligible=[r for r in period['validation'] if r['eligible']]
        selected=max(eligible,key=lambda v:v['selectionScore'])['method'] if eligible else 'baseline'
        period['selected']=selected
        period['selectedByFamily']={f:max([r for r in eligible if r['method'].startswith(f)],key=lambda v:v['selectionScore'])['method'] if any(r['method'].startswith(f) for r in eligible) else 'baseline' for f in ['boost','mlp']}
        period['exitResults']=[]
        for exit in ['fixed2r','atr4']:
            r=evaluate(start,end,candidates.get(selected),exit=exit,stress=True);r.update(method=exit,selector=selected);period['exitResults'].append(r)
            print(json.dumps(dict(year=year,exit=exit,selector=selected,test=r['return'],dd=r['maxDrawdown'])),flush=True)
        report['periods'].append(period)
        (OUT/'checkpoint.json').write_text(json.dumps(report,ensure_ascii=False,separators=(',',':')))
    worker.stdin.close();worker.wait()
    previous=json.loads((ROOT/'simulation/cpd-research/latest.json').read_text())
    for p in report['periods']:
        old=next(x['results'][0] for x in previous['periods'] if x['year']==p['year'])
        assert abs(old['equity']-p['results'][0]['equity'])<1e-5,('Baseline drift',p['year'])
    report['baselineReproduction']='All annual baseline equity values reproduce the previous CPD experiment within $0.00001.'
    report['sampleHash']=hashlib.sha256(Path('/tmp/selector-samples.json').read_bytes()).hexdigest()
    report['sourceHashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'scripts'/s for s in ['selector_data.cjs','selector_worker.cjs','train_selector.py','paper_engine.cjs','trend_methods.cjs']]}
    # Keep exact full records, no evaluation-period winner promotion.
    (OUT/'latest.json').write_text(json.dumps(report,ensure_ascii=False,separators=(',',':')))
    print('COMPLETED',flush=True)
if __name__=='__main__':build()
