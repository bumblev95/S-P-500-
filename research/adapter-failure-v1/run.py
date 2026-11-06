"""Offline, quarantined diagnostic. Writes only this experiment's output directory."""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import sys
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'reuse'))
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
import build_adaptive_research as adapter
from research_joint_indicator import label, date_weights, split_matured, ordered_probability

BASES = ('original', 'noChange', 'trend')
PRICE = ('original', 'noChange', 'trend', 'biasCorrected', 'regimeBlend',
         'fixed90original10noChange', 'causalMapeBlend', 'causalJointBlend')
DIRECTION = ('directionLogistic', 'directionBalanced', 'directionTree',
             'directionEnsemble', 'conservativeDown')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()

def read_sources():
    manifest = json.loads((HERE/'input-manifest.json').read_text())
    content = {}
    for entry in manifest['files']:
        stored = (HERE/entry['file']).read_bytes()
        raw = gzip.decompress(stored) if entry['file'].endswith('.gz') else stored
        if digest(stored) != entry['sha256'] or digest(raw) != entry['rawSha256']:
            raise ValueError('Frozen source hash mismatch: '+entry['file'])
        content[entry['file']] = raw
    return manifest, content

def validate(rows, source):
    adapter.normalize(source)  # Reuse original duplicate and source-fold clock checks.
    keys = set()
    through = ''
    for origin in sorted({r['origin'] for r in rows}):
        block = [r for r in rows if r['origin'] == origin]
        if origin < through:
            raise ValueError('Overlapping origin blocks cannot be counted as independent')
        through = max(r['targetDate'] for r in block)
        for row in block:
            key = (row['symbol'], origin)
            if key in keys:
                raise ValueError('Duplicate row key')
            keys.add(key)
            fields = ('y', 'original', 'trend', 'ma200', 'vol84', 'rsi14', 'macdHistogram', 'low', 'high')
            if not all(np.isfinite(row[k]) for k in fields):
                raise ValueError('Missing/nonfinite feature: fail whole cohort, never drop row')
            if not origin < row['targetDate'] <= source['generatedAt'][:10]:
                raise ValueError('Unmatured target')
    return keys

def macro_regimes(raw, origins):
    daily = list(csv.DictReader(io.StringIO(raw.decode())))
    dates = [r['date'] for r in daily]
    price = np.array([float(r['signalPrice']) for r in daily])
    result = {}
    for origin in origins:
        indices = [i for i,d in enumerate(dates) if d < origin]
        if not indices or indices[-1] < 200:
            raise ValueError('Insufficient strictly prior SPY history')
        i = indices[-1]
        vol = float(np.std(np.diff(np.log(price[i-63:i+1])), ddof=1)*np.sqrt(252))
        above = price[i] >= price[i-199:i+1].mean()
        result[origin] = dict(name=('above200' if above else 'below200')+
            ('HighVol' if vol >= .2 else 'LowVol'), through=dates[i], vol63=vol,
            priceToMA200=float(price[i]/price[i-199:i+1].mean()-1))
    return result

def metrics(rows, name):
    if not rows:
        return None
    actual = np.exp([r['y'] for r in rows])
    value = np.array([r['methods'][name]['ratio'] for r in rows])
    truth = label(actual)
    predicted = np.array([r['methods'][name]['direction'] for r in rows])
    w = date_weights(rows)
    error = abs(value-actual)
    ape = error/actual
    avg = lambda a: float(np.average(a, weights=w))
    ratio = lambda num, den: float(w[num].sum()/w[den].sum()) if w[den].sum() else None
    recalls = {str(c): ratio((truth==c)&(predicted==c), truth==c) for c in (-1,0,1)}
    down = predicted == -1
    result = dict(n=len(rows), dates=len({r['origin'] for r in rows}),
        mape=avg(ape), returnMae=avg(error), p90Mape=adapter.quantile(ape,w,.9),
        p90ReturnError=adapter.quantile(error,w,.9), signedBias=avg(value-actual),
        directionAccuracy=avg(truth==predicted), alwaysUpAccuracy=avg(truth==1),
        downRecall=recalls['-1'], upRecall=recalls['1'], flatRecall=recalls['0'],
        balancedAccuracy=float(np.mean([v for v in recalls.values() if v is not None])),
        downPrecision=ratio(down&(truth==-1), down), downPrevalence=avg(truth==-1),
        downFalsePositiveRate=ratio(down&(truth!=-1), truth!=-1),
        downWarnings=int(down.sum()), falseDownWarnings=int((down&(truth!=-1)).sum()),
        directionPriceAgreement=avg(predicted==label(value)),
        confusion={str(t):{str(p):int(((truth==t)&(predicted==p)).sum()) for p in (-1,0,1)} for t in (-1,0,1)})
    if 'probability' in rows[0]['methods'][name]:
        prob = np.array([r['methods'][name]['probability'] for r in rows])
        prior = np.array([r['methods'][name]['prior'] for r in rows])
        hot = (truth[:,None]==np.array([-1,0,1])).astype(float)
        result.update(brier=avg(((prob-hot)**2).sum(axis=1)),
                      priorBrier=avg(((prior-hot)**2).sum(axis=1)),
                      logLoss=avg(-np.log(np.clip(prob[np.arange(len(rows)),truth+1],1e-12,1))))
    return result

def joint_checks(candidate, original, protocol, evidence=False):
    tol=1e-12
    def present(x): return x is not None
    checks = dict(mapeNotWorse=candidate['mape'] <= original['mape']+tol,
        returnMaeNotWorse=candidate['returnMae'] <= original['returnMae']+tol,
        tailNotWorse=candidate['p90Mape'] <= original['p90Mape']+tol,
        downRecall=present(candidate['downRecall']) and present(original['downRecall']) and
            candidate['downRecall'] >= original['downRecall']+protocol['minimumDownRecallGain'],
        downPrecision=present(candidate['downPrecision']) and candidate['downPrecision'] >=
            max(original['downPrecision'] or 0., candidate['downPrevalence']+protocol['minimumDownPrecisionLift']),
        falseDownNotWorse=present(candidate['downFalsePositiveRate']) and
            candidate['downFalsePositiveRate'] <= original['downFalsePositiveRate']+tol,
        upRecallNotWorse=present(candidate['upRecall']) and present(original['upRecall']) and
            candidate['upRecall']+tol >= original['upRecall'],
        balancedDirection=candidate['balancedAccuracy']+tol >= original['balancedAccuracy'],
        accuracy=candidate['directionAccuracy'] > max(original['directionAccuracy'],candidate['alwaysUpAccuracy']),
        warningCount=candidate['downWarnings'] >= protocol['minimumDownWarnings'])
    if 'brier' in candidate:
        checks['probability'] = candidate['brier'] < candidate['priorBrier']
    if evidence:
        checks.update(enoughIndependentDates=candidate['dates'] >= protocol['minimumEvaluationDates'],
                      pitComplete=False, untouchedProspectiveEvidence=False)
    return {k:bool(v) for k,v in checks.items()}

def features(rows):
    return np.array([[r['original'],r['trend'],r['ma200'],r['vol84'],r['rsi14'],
        r['macdHistogram'],r['high']-r['low'],r['high']+r['low']] for r in rows])

def classifiers(all_rows, test, protocol):
    # PR25 label/split functions use price ratios; keep source y as log ratios.
    ratio_rows = [dict(r,y=float(np.exp(r['y']))) for r in all_rows]
    split = split_matured(ratio_rows, test[0]['origin'], protocol)
    if split is None:
        raise ValueError('Insufficient fit/calibration; refuse reduced comparison cohort')
    fit,cal,matured = split
    x=features(fit); y=label([r['y'] for r in fit]); w=date_weights(fit)
    z=protocol['classifierSettings']
    prior=np.array([w[y==c].sum() for c in (-1,0,1)]);prior/=prior.sum()
    outputs={}
    for name in DIRECTION[:3]:
        train_w=w.copy()
        if name!='directionLogistic':
            train_w *= np.array([prior[int(c)+1]**-.5 for c in y])
            train_w *= len(train_w)/train_w.sum()
        scaler=None
        if name=='directionTree':
            model=HistGradientBoostingClassifier(max_iter=z['treeIterations'], max_leaf_nodes=z['treeLeaves'],
                min_samples_leaf=z['treeLeafMinimum'],l2_regularization=z['treeL2'],
                learning_rate=z['treeLearningRate'],early_stopping=False,random_state=z['seed'])
        else:
            scaler=StandardScaler().fit(x,sample_weight=w)
            model=LogisticRegression(C=z['logisticC'],max_iter=500,random_state=z['seed'])
        transform=lambda rows: scaler.transform(features(rows)) if scaler else features(rows)
        model.fit(transform(fit),y,sample_weight=train_w)
        cal_raw=ordered_probability(model,transform(cal))
        calibrator=LogisticRegression(C=z['calibratorC'],max_iter=500,random_state=z['seed'])
        calibrator.fit(np.log(np.clip(cal_raw,1e-6,1)),label([r['y'] for r in cal]),sample_weight=date_weights(cal))
        raw=ordered_probability(model,transform(test))
        outputs[name]=ordered_probability(calibrator,np.log(np.clip(raw,1e-6,1)))
    outputs['directionEnsemble']=np.mean([outputs[n] for n in DIRECTION[:3]],axis=0)
    outputs['conservativeDown']=outputs['directionEnsemble']
    clocks=dict(origin=test[0]['origin'],fitDates=sorted({r['origin'] for r in fit}),
        fitTargetThrough=max(r['targetDate'] for r in fit),calibrationDates=sorted({r['origin'] for r in cal}),
        calibrationTargetThrough=max(r['targetDate'] for r in cal),
        fitN=len(fit),calibrationN=len(cal),prior=prior.tolist())
    assert clocks['fitTargetThrough']<clocks['calibrationDates'][0]
    assert clocks['calibrationTargetThrough']<clocks['origin']
    return outputs, prior, clocks

def price_method(ratio):
    return dict(ratio=float(ratio),direction=int(label(ratio)))

def blended(rows, mix, key='candidate'):
    result=[]
    for r in rows:
        value=float(sum(v*np.exp(r[b]) for b,v in zip(BASES,mix)))
        result.append(dict(r,methods={'original':price_method(np.exp(r['original'])),key:price_method(value)}))
    return result

def choose_blends(source, origin, protocol):
    prior=adapter.matured(source,origin)
    if len({r['origin'] for r in prior})<protocol['minimumBlendDates']:
        raise ValueError('Insufficient blend calibration')
    options=[]
    for a in range(5):
        for b in range(5-a):
            mix=(a/4,b/4,(4-a-b)/4)
            score_rows=blended(prior,mix)
            c=metrics(score_rows,'candidate');old=metrics(score_rows,'original')
            checks=joint_checks(c,old,protocol)
            options.append(dict(mix=mix,metrics=c,checks=checks))
    # Prefer original in an exact tie, then less trend allocation.
    sort=lambda q:(q['metrics']['mape'],-q['mix'][0],q['mix'][2])
    error=min(options,key=sort)
    joint_options=[q for q in options if all(q['checks'].values())]
    joint=min(joint_options,key=lambda q:(-q['metrics']['balancedAccuracy'],*sort(q))) if joint_options else None
    return error['mix'],joint['mix'] if joint else (1.,0.,0.), dict(origin=origin,
        targetThrough=max(r['targetDate'] for r in prior),dates=sorted({r['origin'] for r in prior}),
        errorMix=list(error['mix']),jointMix=list(joint['mix']) if joint else [1.,0.,0.],
        jointFeasible=bool(joint_options),jointFeasibleOptions=len(joint_options),
        options=options)

def original_adapter_replay(source, stored_rows, summary):
    all_rows=adapter.normalize(source)
    computed=[];through=''
    for origin in sorted({r['origin'] for r in all_rows}):
        block=[r for r in all_rows if r['origin']==origin]
        if origin<through:continue
        through=max(r['targetDate'] for r in block)
        pooled=adapter.fit(all_rows,origin)
        if pooled is None:continue
        local={g:adapter.fit([r for r in all_rows if adapter.regime(r)==g],origin) for g in {adapter.regime(r) for r in block}}
        for r in block:
            computed.append(dict(r,**adapter.predict(r,pooled,local.get(adapter.regime(r)))))
    if {(r['symbol'],r['origin']) for r in computed}!={(r['symbol'],r['origin']) for r in stored_rows}:
        raise ValueError('Adapter replay population mismatch')
    by={(r['symbol'],r['origin']):r for r in computed}
    for r in stored_rows:
        for name in ('biasCorrected','regimeBlend'):
            if not np.isclose(r[name],by[r['symbol'],r['origin']][name],rtol=0,atol=1e-14):
                raise ValueError('Adapter prediction replay mismatch')
    comparison=adapter.compare(stored_rows)
    reference=summary['horizons']['126']['comparison']
    differences=[]
    def same(a,b):
        if isinstance(a,dict):return set(a)==set(b) and all(same(a[k],b[k]) for k in a)
        if isinstance(a,list):return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
        if isinstance(a,float) and isinstance(b,(float,int)):
            differences.append(abs(a-b))
            return abs(a-b)<=1e-14
        return a==b
    if not same(comparison,reference):
        raise ValueError('Adapter final comparison replay mismatch')
    return all_rows,dict(predictionsMatchWithinTolerance=True,comparisonMatchWithinTolerance=True,tolerance=1e-14,
        maxMetricAbsoluteDifference=max(differences,default=0),checksExact=comparison['checks']==reference['checks'],
        rows=len(stored_rows),comparison=reference)

def ci(values):
    # Exact iid date-block bootstrap enumeration, descriptive with only four dates.
    n=len(values)
    draws=[np.mean([values[i] for i in indices]) for indices in itertools.product(range(n),repeat=n)]
    return [float(v) for v in np.quantile(draws,[.025,.975])]

def diagnostics(rows):
    names=PRICE+DIRECTION
    groups={'all':rows}
    for field in ('stockRegime','marketRegime','truthLabel','errorBin'):
        for value in sorted({str(r[field]) for r in rows}):
            groups[field+':'+value]=[r for r in rows if str(r[field])==value]
    groups.update({'origin:'+d:[r for r in rows if r['origin']==d] for d in sorted({r['origin'] for r in rows})})
    scores={group:{n:metrics(block,n) for n in names} for group,block in groups.items()}
    paired={}
    for group,block in groups.items():
        old=scores[group]['original'];new=scores[group]['biasCorrected']
        w=date_weights(block);d=np.array([abs(np.exp(r['biasCorrected'])-np.exp(r['y']))-abs(np.exp(r['original'])-np.exp(r['y'])) for r in block])
        flips=[r for r in block if r['methods']['original']['direction']!=r['methods']['biasCorrected']['direction']]
        paired[group]=dict(n=len(block),mapeChange=new['mape']-old['mape'],returnMaeChange=new['returnMae']-old['returnMae'],
            directionChange=new['directionAccuracy']-old['directionAccuracy'],
            improvedErrorRows=int((d<0).sum()),worsenedErrorRows=int((d>0).sum()),
            directionFlips=len(flips),correctToWrong=sum(r['methods']['original']['direction']==r['truthLabel'] for r in flips),
            wrongToCorrect=sum(r['methods']['biasCorrected']['direction']==r['truthLabel'] for r in flips),
            dateEqualContributionToReturnMaeChange=float(np.dot(w,d)/w.sum()))
    return scores,paired

def run(out):
    out=out.resolve()
    if HERE not in out.parents:raise ValueError('Output must remain inside isolated experiment')
    protocol=json.loads((HERE/'PROTOCOL.json').read_text())
    manifest,content=read_sources()
    load=lambda n:json.loads(content['sources/'+n])
    source=load('validation-126.json.gz');stored=load('adaptive-126.json.gz')['rows'];summary=load('adaptive-summary.json.gz')
    validate(adapter.normalize(source),source)
    all_rows,replay=original_adapter_replay(source,stored,summary)
    start=protocol['evaluationStart']
    if start!=replay['comparison']['evaluationStart']:raise ValueError('Holdout boundary drift')
    test_rows=[r for r in stored if r['origin']>=start]
    macro=macro_regimes(content['sources/spy-input.csv.gz'],sorted({r['origin'] for r in test_rows}))
    results=[];folds=[];blend_folds=[]
    for origin in sorted(macro):
        block=[r for r in test_rows if r['origin']==origin]
        probabilities,prior,clock=classifiers(all_rows,block,protocol)
        error_mix,joint_mix,blend_clock=choose_blends(all_rows,origin,protocol)
        folds.append(clock);blend_folds.append(blend_clock)
        for i,r in enumerate(block):
            methods={n:price_method(np.exp(r[n])) for n in PRICE[:5]}
            methods['fixed90original10noChange']=price_method(.9*np.exp(r['original'])+.1)
            for n,mix in [('causalMapeBlend',error_mix),('causalJointBlend',joint_mix)]:
                methods[n]=price_method(sum(v*np.exp(r[b]) for b,v in zip(BASES,mix)))
            for n in DIRECTION:
                p=probabilities[n][i]
                direction=int(np.argmax(p))-1
                if n=='conservativeDown':
                    direction=-1 if p[0]>=.65 and p[0]>p[2] else methods['original']['direction']
                methods[n]=dict(ratio=methods['original']['ratio'],direction=direction,probability=p.tolist(),prior=prior.tolist())
            ape=abs(np.exp(r['original']-r['y'])-1)
            results.append(dict(r,methods=methods,truthLabel=int(label(np.exp(r['y']))),
                stockRegime=adapter.regime(r),marketRegime=macro[origin]['name'],
                errorBin='<=10%' if ape<=.1 else '10-30%' if ape<=.3 else '>30%'))
    expected={(r['symbol'],r['origin']) for r in test_rows}
    if expected!={(r['symbol'],r['origin']) for r in results}:raise ValueError('Unequal final population')
    scores,paired=diagnostics(results)
    gates={};uncertainty={}
    dates=sorted(macro)
    for name in PRICE[3:]+DIRECTION:
        g=joint_checks(scores['all'][name],scores['all']['original'],protocol,evidence=True)
        differences=[scores['origin:'+d]['original']['mape']-scores['origin:'+d][name]['mape'] for d in dates]
        accuracy_diff=[scores['origin:'+d][name]['directionAccuracy']-scores['origin:'+d][name]['alwaysUpAccuracy'] for d in dates]
        joint_date=[scores['origin:'+d][name]['mape']<=scores['origin:'+d]['original']['mape']+1e-12 and
                    scores['origin:'+d][name]['directionAccuracy']>=scores['origin:'+d]['original']['directionAccuracy'] and
                    scores['origin:'+d][name]['downFalsePositiveRate']<=scores['origin:'+d]['original']['downFalsePositiveRate']+1e-12 for d in dates]
        uncertainty[name]=dict(mapeImprovementDateBootstrap95=ci(differences),
                              accuracyVsAlwaysUpDateBootstrap95=ci(accuracy_diff),
                              independentDates=len(dates),notProspective=True)
        g.update(dateConsistency=bool(np.mean(joint_date)>=.6),
                 errorEvidence=ci(differences)[0]>=-1e-12,
                 directionEvidence=ci(accuracy_diff)[0]>0)
        gates[name]=dict(checks=g,passed=all(g.values()),eligible=False,failed=[k for k,v in g.items() if not v])
    errors=np.array([[np.exp(r[n])-np.exp(r['y']) for n in BASES] for r in results])
    correlation=np.corrcoef(errors,rowvar=False).tolist()
    # Decomposition contributions use FULL-cohort date weights, not per-group renormalization.
    full_w=adapter.weights(results);full_w/=full_w.sum()
    contributions={}
    for field in ('truthLabel','stockRegime','errorBin'):
        contributions[field]={}
        for value in sorted({str(r[field]) for r in results}):
            mask=np.array([str(r[field])==value for r in results])
            delta=np.array([abs(np.exp(r['biasCorrected'])-np.exp(r['y']))-abs(np.exp(r['original'])-np.exp(r['y'])) for r in results])
            contributions[field][value]=float(np.dot(full_w[mask],delta[mask]))
    pit=load('pr25-pit-audit.json.gz');lifecycle=load('pr25-lifecycle-audit.json.gz')
    report=dict(version=protocol['version'],status='quarantined_diagnostic',sourceManifestHash=digest((HERE/'input-manifest.json').read_bytes()),
        protocolHash=digest((HERE/'PROTOCOL.json').read_bytes()),codeHash=digest(Path(__file__).read_bytes()),python=sys.version.split()[0],numpy=np.__version__,sklearn=sklearn.__version__,
        replay=replay,macroRegimes=macro,paired=paired,scores=scores,uncertainty=uncertainty,
        gates=gates,classifierFolds=folds,blendFolds=blend_folds,errorCorrelation=dict(methods=list(BASES),matrix=correlation),
        contributions=contributions,pr25Reuse=dict(commit=manifest['pr25Head'],pitReady=pit['readyOriginCount'],pitOrigins=pit['originCount'],
        lifecycleStatus=lifecycle.get('status'),functions=['label','date_weights','split_matured','ordered_probability'],
        excludedDuplicateWork=['PR25 joint distribution','PR25 blends','drawdown path collection','PIT baseline reconstruction']),
        newOriginsPitReady=0,eligible=False,selectedCandidate=None,productionChanged=False,tradingChanged=False)
    out=out.resolve()
    if HERE not in out.parents:raise ValueError('Output must remain inside isolated experiment')
    out.mkdir(parents=True,exist_ok=True)
    (out/'results.json').write_bytes(canonical(report))
    (out/'predictions.json.gz').write_bytes(gzip.compress(canonical(results),mtime=0))
    table=[]
    for group,methods in scores.items():
        for name,m in methods.items():table.append(dict(group=group,method=name,**{k:v for k,v in m.items() if not isinstance(v,dict)}))
    with (out/'metrics.csv').open('w',newline='') as f:
        columns=sorted({k for r in table for k in r});writer=csv.DictWriter(f,fieldnames=columns,lineterminator='\n');writer.writeheader();writer.writerows(table)
    hashes={f.name:digest(f.read_bytes()) for f in sorted(out.iterdir()) if f.name in ('results.json','predictions.json.gz','metrics.csv')}
    (out/'verification.json').write_bytes(canonical(dict(outputHashes=hashes,sourceHashesVerified=True,
        adapterPredictionsReplayWithinTolerance=True,adapterComparisonReplayWithinTolerance=True,tolerance=1e-14,identicalCohort=True,
        constantPricesForDirectionCandidates=all(r['methods'][n]['ratio']==r['methods']['original']['ratio'] for r in results for n in DIRECTION))))
    for n,m in scores['all'].items():
        print(n, 'MAPE',round(m['mape']*100,4),'accuracy',round(m['directionAccuracy']*100,3),
              'downRecall',round((m['downRecall'] or 0)*100,3),'FPR',round((m['downFalsePositiveRate'] or 0)*100,3),flush=True)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=HERE/'output');args=parser.parse_args()
    with threadpool_limits(limits=2):run(args.output)
