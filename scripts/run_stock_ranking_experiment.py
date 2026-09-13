"""E1: four predeclared 252-day regressions, scored as stock rankings."""
import os
os.environ.setdefault('OMP_NUM_THREADS','2')
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone
import hashlib,json,math,time,platform
import numpy as np
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
import sklearn,scipy
from build_forecasts import atomic_json
from build_environment_research import records,features,PROXIES,HORIZON_PROFILES
from audit_stock_experiment_inputs import audit

ROOT=Path(__file__).resolve().parents[1]
EXP=ROOT/'research/experiments/2026-09-13'
NAMES=('ridgeAbsolute','ridgeRelative','treeAbsolute','treeRelative')
PINNED={
 'research/inputs.json':'76bbcdc6d0c8204d1924037108c98cbb1ac342ced5856e61269bb8c24173ec5d',
 'research/earnings.json':'d0b3bf61dd837551e253246e11ec111c337f8a2ac22fbc372e0b15bd287c5f3e',
 'research/universe.json':'5e320b8c590df1caee44ebdc6ab11260d029c09ed55991a3641533033749d48d',
}

def prepare(root):
    audit(root)
    for name,sha in PINNED.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha:
            raise ValueError('Frozen input changed: '+name)
    baseline=json.loads((root/'research/environment.json').read_text())
    members=json.loads((root/'research/universe.json').read_text())['members']
    history={s:json.loads((root/'research/history'/(s.replace('^','INDEX_')+'.json')).read_text())['prices']
             for s in set(baseline['stockUniverse'])|set(PROXIES)}
    context={}
    for s in PROXIES:
        f=features(history[s]);context[s]=dict(features=f,dates=np.array(sorted(f)))
    inputs=json.loads((root/'research/inputs.json').read_text())
    inputs['earnings']=json.loads((root/'research/earnings.json').read_text())['issuers']
    inputs['symbolCIKs']={s:v['cik'] for s,v in members.items()}
    rows,latest=records({s:history[s] for s in baseline['stockUniverse']},context,252,'stocks',inputs)
    print('Prepared weekly rows:',len(rows),'latest issuers/share classes:',len(latest),flush=True)
    spy={r['date']:r['close'] for r in history['SPY']}
    indices={s:{p['date']:i for i,p in enumerate(prices)} for s,prices in history.items()}
    X=np.array([r['w']+[float(r['regime'].startswith('하락')),float('고변동' in r['regime'])] for r in rows])
    absolute=np.log([r['y'] for r in rows])
    market=np.log([spy[r['targetDate']]/spy[r['origin']] for r in rows])
    meta=[]
    for r in rows:
        s=r['symbol'];i=indices[s][r['origin']]
        entry=history[s][i+1];target=history[s][indices[s][r['targetDate']]]
        if entry['date']>target['date']:raise ValueError('Entry follows target')
        meta.append({k:r[k] for k in ('symbol','origin','targetDate','y','contextThrough','inputThrough')}|
                    dict(momentum=r['x'][3],entryDate=entry['date'],
                         stockGross=target['close']/entry['close'],
                         spyGross=spy[r['targetDate']]/spy[entry['date']]))
    # Compact arrays avoid retaining the multiple feature copies in legacy rows.
    del rows,inputs,context
    archived={(r['symbol'],r['origin']):r for r in baseline['stocks']['252']['outcomes']}
    found=set()
    for r in meta:
        key=(r['symbol'],r['origin'])
        if key in archived:
            if r['targetDate']!=archived[key]['targetDate'] or abs(r['y']-archived[key]['y'])>1e-12:
                raise ValueError('E1 changed the archived evaluation sample')
            found.add(key)
    if found!=set(archived):raise ValueError('Missing archived evaluation rows')
    return dict(X=X,Y=np.column_stack([absolute,absolute-market]),meta=meta,baseline=baseline,
                latest=latest,history=history,members=members)

def train_weights(meta):
    sizes=Counter(r['origin'] for r in meta)
    return np.array([len(meta)/(len(sizes)*sizes[r['origin']]) for r in meta])

def ridge_design(train,test,weights):
    # Fit medians only to past training rows. All-missing columns stay explicit.
    medians=np.array([np.median(col[np.isfinite(col)]) if np.any(np.isfinite(col)) else 0. for col in train.T])
    def transform(x):
        missing=~np.isfinite(x)
        return np.column_stack([np.where(missing,medians,x),missing.astype(float)])
    a=transform(train);b=transform(test)
    scale=StandardScaler().fit(a,sample_weight=weights)
    return scale.transform(a),scale.transform(b)

def fit_predict(X,Y,meta,testX,origin,tree_profile=None):
    train=np.array([r['targetDate']<origin for r in meta])
    if not train.any():raise ValueError('No matured training rows')
    selected=[r for r,yes in zip(meta,train) if yes]
    if any(r['origin']>=origin for r in selected):raise ValueError('Invalid chronology')
    weights=train_weights(selected);tx=X[train];ty=Y[train]
    design,test=ridge_design(tx,testX,weights)
    model=Ridge(alpha=100.,fit_intercept=True,solver='cholesky')
    rp=model.fit(design,ty,sample_weight=weights).predict(test)
    params={k:v for k,v in (tree_profile or HORIZON_PROFILES[252]).items()
            if k in ('max_iter','max_leaf_nodes','min_samples_leaf','l2_regularization','learning_rate')}
    result=dict(ridgeAbsolute=rp[:,0],ridgeRelative=rp[:,1])
    for i,name in enumerate(('treeAbsolute','treeRelative')):
        model=HistGradientBoostingRegressor(loss='absolute_error',**params,early_stopping=False,random_state=275)
        result[name]=model.fit(tx,ty[:,i],sample_weight=weights).predict(testX)
    return result,dict(trainingRows=len(selected),trainingOrigins=len(set(r['origin'] for r in selected)),
                       trainTargetThrough=max(r['targetDate'] for r in selected))

def safe_ic(values,actual):
    if len(values)<3 or len(set(values))<2 or len(set(actual))<2:return 0.
    return float(spearmanr(values,actual).statistic)

def evaluate(rows,name,sectors=None):
    by=defaultdict(list)
    for r in rows:by[r['origin']].append(r)
    dates={}
    for origin,rr in sorted(by.items()):
        chosen=sorted(rr,key=lambda r:(-r[name],r['symbol']))[:math.ceil(.2*len(rr))]
        costs={}
        for bps in (5,10,25):
            fee=bps/10000
            net=lambda gross:gross*(1-fee)/(1+fee)-1
            costs[str(bps)]=dict(selected=float(np.mean([net(r['stockGross']) for r in chosen])),
                equalWeight=float(np.mean([net(r['stockGross']) for r in rr])),
                spy=float(np.mean([net(r['spyGross']) for r in rr])))
        dates[origin]=dict(n=len(rr),ic=safe_ic([r[name] for r in rr],[r['y'] for r in rr]),
            selectedCount=len(chosen),costs=costs,
            selectedSymbols=[r['symbol'] for r in chosen],
            currentSectorExposure=dict(Counter((sectors or {}).get(r['symbol'],'Unknown') for r in chosen)),
            meanEntryDelayDays=float(np.mean([(datetime.fromisoformat(r['entryDate'])-datetime.fromisoformat(origin)).days for r in rr])),
            targetThrough=max(r['targetDate'] for r in rr))
    metrics=dict(n=len(rows),dates=len(dates),dateMeanIc=float(np.mean([v['ic'] for v in dates.values()])) if dates else None,
        positiveIcFraction=float(np.mean([v['ic']>0 for v in dates.values()])) if dates else None,byDate=dates)
    if name in ('ridgeAbsolute','treeAbsolute') and rows:
        errors=np.array([abs(math.exp(np.clip(r[name],-20,20))/r['y']-1) for r in rows])
        metrics['diagnosticMape']=float(errors.mean())
    return metrics

def select(earlier):
    eligible=[name for name in NAMES if earlier[name]['dateMeanIc']>0 and
              earlier[name]['dateMeanIc']>earlier['momentum']['dateMeanIc']]
    return max(eligible,key=lambda n:(earlier[n]['dateMeanIc'],n)) if eligible else None

def date_uncertainty(metrics,benchmark):
    dates=sorted(set(metrics['byDate'])&set(benchmark['byDate']))
    diff=np.array([metrics['byDate'][d]['ic']-benchmark['byDate'][d]['ic'] for d in dates])
    # Descriptive paired date-bootstrap, not a claim that eight dates are IID.
    rng=np.random.default_rng(23)
    means=diff[rng.integers(0,len(diff),size=(10000,len(diff)))].mean(axis=1)
    return dict(nDates=len(dates),meanIcDifference=float(diff.mean()),
        descriptiveDateBootstrap95=[float(v) for v in np.quantile(means,[.025,.975])],
        interpretation='Descriptive paired date resampling. Few, potentially dependent market dates; not confirmatory.')

def issue_research_scores(ds,folder,manifest):
    path=folder/'e1-issued.json'
    if path.exists():
        print('Preserving the existing immutable research issuance',flush=True)
        return
    newest=max(r['origin'] for r in ds['latest'].values())
    if (datetime.now(timezone.utc).date()-datetime.fromisoformat(newest).date()).days>7:
        raise ValueError('Frozen input is too old for a new prospective issuance')
    chosen={}
    for symbol,r in sorted(ds['latest'].items()):
        if r['origin']==newest:
            chosen.setdefault(ds['members'][symbol]['cik'],r)
    rows=list(chosen.values())
    x=np.array([r['w']+[float(r['regime'].startswith('하락')),float('고변동' in r['regime'])] for r in rows])
    predictions,status=fit_predict(ds['X'],ds['Y'],ds['meta'],x,newest)
    issued=dict(experiment=manifest['experiment'],issuedAt=datetime.now(timezone.utc).isoformat(),
        codeHash=manifest['codeHash'],protocolHash=manifest['protocolHash'],asOf=newest,
        horizonTradingDays=252,training=status,status='research_only_awaiting_future_outcomes',
        entryRule='First tradable closing price strictly after issuedAt; retain both as-of and execution-based outcomes.',
        productionPromoted=False,
        predictions=[dict(symbol=r['symbol'],anchor=r['anchor'],
            scores={name:float(values[i]) for name,values in predictions.items()}) for i,r in enumerate(rows)])
    with path.open('x') as handle:
        json.dump(issued,handle,ensure_ascii=False,allow_nan=False,indent=2)
        handle.write('\n')
    print('Issued immutable research scores:',len(rows),issued['issuedAt'],flush=True)

def build(root=ROOT):
    folder=root/'research/experiments/2026-09-13';folder.mkdir(parents=True,exist_ok=True)
    manifest=dict(experiment='stock-validation-e1-v1',startedAt=datetime.now(timezone.utc).isoformat(),
        codeHash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        protocolHash=hashlib.sha256((folder/'PROTOCOL.md').read_bytes()).hexdigest(),
        versions=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,sklearn=sklearn.__version__),
        configurations=list(NAMES),prospective=False,productionPromoted=False)
    atomic_json(folder/'e1-manifest.json',manifest)
    ds=prepare(root);g=ds['baseline']['stocks']['252'];comparison=g['comparison']
    origins=[f['origin'] for f in g['folds']];outcomes=[];folds=[]
    for origin in origins:
        tick=time.monotonic()
        ids=np.array([i for i,r in enumerate(ds['meta']) if r['origin']==origin])
        print('E1 fit',origin,'test',len(ids),flush=True)
        predictions,status=fit_predict(ds['X'],ds['Y'],ds['meta'],ds['X'][ids],origin)
        for offset,i in enumerate(ids):
            r=dict(ds['meta'][i]);r.update({k:float(v[offset]) for k,v in predictions.items()});outcomes.append(r)
        folds.append(dict(origin=origin,**status,seconds=time.monotonic()-tick))
        print('E1 completed',origin,'seconds',round(folds[-1]['seconds'],1),flush=True)
        # A checkpoint preserves each completed fit if a later stage fails.
        atomic_json(folder/'e1-checkpoint.json',dict(manifest=manifest,folds=folds,outcomes=outcomes))
    sectors={s:v['sector'] for s,v in ds['members'].items()}
    earlier=[r for r in outcomes if r['origin'] in comparison['selectionDates'] and r['targetDate']<comparison['evaluationStart']]
    later=[r for r in outcomes if r['origin']>=comparison['evaluationStart']]
    scores={section:{k:evaluate(rows,k,sectors) for k in (*NAMES,'momentum')}
            for section,rows in (('selection',earlier),('evaluation',later))}
    selected=select(scores['selection'])
    uncertainty={k:date_uncertainty(v,scores['evaluation']['momentum']) for k,v in scores['evaluation'].items() if k!='momentum'}
    laterchecks={}
    if selected:
        m=scores['evaluation'][selected];control=scores['evaluation']['momentum']
        laterchecks=dict(positiveIc=m['dateMeanIc']>0,beatsMomentum=m['dateMeanIc']>control['dateMeanIc'],
            conservativeIcDifference=uncertainty[selected]['descriptiveDateBootstrap95'][0]>0,
            enoughDates=m['dates']>=6)
        for bps in ('5','10','25'):
            delta=[d['costs'][bps]['selected']-max(d['costs'][bps]['equalWeight'],
                   control['byDate'][day]['costs'][bps]['selected'],d['costs'][bps]['spy'])
                   for day,d in m['byDate'].items()]
            laterchecks['netCohortImprovement'+bps]=float(np.mean(delta))>0
    result=dict(**manifest,completedAt=datetime.now(timezone.utc).isoformat(),folds=folds,
        sample=dict(earlier=len(earlier),later=len(later),expectedLater=g['comparison']['evaluation']['noChange']['n']),
        selected=selected,selectionEligible=selected is not None,laterChecks=laterchecks,
        laterEligible=bool(selected and all(laterchecks.values())),scores=scores,uncertainty=uncertainty,
        originalPricePassed=comparison['passed'],
        cohortLimitations='Sparse disjoint cohorts entered at next close. Not annualized and not a continuous portfolio backtest. Current sector labels are descriptive only.',
        outcomeHash=hashlib.sha256(json.dumps(outcomes,sort_keys=True,allow_nan=False).encode()).hexdigest())
    if len(later)!=result['sample']['expectedLater']:raise ValueError('Later sample mismatch')
    atomic_json(folder/'e1-ranking.json',result)
    lines=['# E1: 12개월 종목 순위 실험','',
        '같은 16개 과거 시작일, 4개 고정 모델을 비교했다. 재사용한 과거 평가이며 신규 실전 검증이 아니다.','',
        '| 모델 | 앞선 날짜 평균 IC | 후반 날짜 평균 IC | 후반 양수 날짜 비율 |',
        '|---|---:|---:|---:|']
    for k in (*NAMES,'momentum'):
        a=scores['selection'][k];b=scores['evaluation'][k]
        lines.append(f"| {k} | {a['dateMeanIc']:.4f} | {b['dateMeanIc']:.4f} | {100*b['positiveIcFraction']:.1f}% |")
    lines+=['',f"앞선 구간에서 선정: {selected or '적격 후보 없음'}.",f"후반 조건 충족: {result['laterEligible']}. 기존 가격 모델 승격: 없음.",'',
        'IC는 종목별 예측 순위와 실현 수익률 순위의 상관계수이며 적중률이나 투자 수익률이 아니다.',
        '포트폴리오 진단과 날짜별 불확실성은 e1-ranking.json에 보관한다. 8개 후반 날짜만으로 확정적 성능을 주장하지 않는다.']
    (folder/'E1-RESULTS.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines),flush=True)
    issue_research_scores(ds,folder,manifest)
    return result

if __name__=='__main__':build()
