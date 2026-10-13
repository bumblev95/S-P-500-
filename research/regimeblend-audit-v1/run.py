"""Offline audit of frozen snapshots; writes only an isolated child directory."""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import build_adaptive_research as guarded


def legacy_module():
    spec = importlib.util.spec_from_file_location('frozen_regimeblend_adapter', HERE/'reuse/build_adaptive_research.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


legacy = legacy_module()
METHODS = (*legacy.BASES, *legacy.VARIANTS)
COMPONENTS = ('pooledOnly', 'blendWithoutBias', 'originalPlusBlendBias')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()


def read_sources(directory=HERE):
    manifest = json.loads((directory/'input-manifest.json').read_text())
    content = {}
    for entry in manifest['files']:
        stored = (directory/entry['file']).read_bytes()
        raw = gzip.decompress(stored) if entry['file'].endswith('.gz') else stored
        if digest(stored) != entry['sha256'] or digest(raw) != entry['rawSha256']:
            raise ValueError('Frozen source hash mismatch: '+entry['file'])
        content[entry['file']] = raw
    return manifest, content


def equivalent(actual, expected, tolerance=1e-14):
    if isinstance(actual, dict):
        return isinstance(expected, dict) and actual.keys() == expected.keys() and all(
            equivalent(actual[k], expected[k], tolerance) for k in actual)
    if isinstance(actual, list):
        return isinstance(expected, list) and len(actual) == len(expected) and all(
            equivalent(a, b, tolerance) for a, b in zip(actual, expected))
    if isinstance(actual, float) and isinstance(expected, (int, float)):
        return abs(actual-expected) <= tolerance
    return actual == expected


def replay(source, saved, summary):
    rows = legacy.normalize(source); guarded.normalize(source)
    if source['model'] != summary['sourceModel'] or source['generatedAt'] != summary['sourceGeneratedAt']:
        raise ValueError('Mismatched model/source clock')
    guarded.validate_comparison_rows(saved)
    computed = []; through = ''; components = {}; clocks = []
    for origin in sorted({r['origin'] for r in rows}):
        block = [r for r in rows if r['origin'] == origin]
        if origin < through: continue
        through = max(r['targetDate'] for r in block)
        pooled = legacy.fit(rows, origin)
        if pooled is None: continue
        local = {g:legacy.fit([r for r in rows if legacy.regime(r) == g], origin)
                 for g in {legacy.regime(r) for r in block}}
        bands = {v:legacy.band(computed, origin, v) for v in legacy.VARIANTS}
        clocks.append(dict(origin=origin, targetThrough=pooled['targetThrough'],
                           dates=pooled['dates'], localTargetThrough={g:v['targetThrough'] for g,v in local.items() if v}))
        for row in block:
            fitted = local.get(legacy.regime(row)) or pooled
            point = legacy.predict(row, pooled, local.get(legacy.regime(row)))
            computed.append(dict(row, **point, bands=bands, correctionTargetThrough=pooled['targetThrough']))
            key = (row['symbol'], origin)
            components[key] = dict(
                pooledOnly=legacy.predict(row, pooled)['regimeBlend'],
                blendWithoutBias=sum(row[b]*fitted['weights'][b] for b in legacy.BASES),
                originalPlusBlendBias=row['original']+fitted['blendBias'],
                blendWeights=fitted['weights'], blendBias=fitted['blendBias'],
                localFit=local.get(legacy.regime(row)) is not None,
                localTargetThrough=fitted['targetThrough'])
    if not equivalent(computed, saved):
        raise ValueError('Full-cohort adapter prediction/band/provenance replay mismatch')
    comparison = legacy.compare(saved)
    if not equivalent(comparison, summary['horizons']['126']['comparison']):
        raise ValueError('Frozen comparison replay mismatch')
    return dict(rows=rows, components=components, clocks=clocks, comparison=comparison,
                verification=dict(fullRows=len(saved), finalRows=comparison['evaluation']['original']['n'],
                    predictionBandProvenanceMatch=True, comparisonMatch=True, tolerance=1e-14))


def metrics(rows, name, weights=None):
    if not rows: raise ValueError('Empty metric cohort')
    w = legacy.weights(rows) if weights is None else np.asarray(weights)
    actual = np.expm1([r['y'] for r in rows]); predicted = np.expm1([r[name] for r in rows])
    error = abs(predicted-actual); ape = error/(1+actual)
    truth = guarded.direction([r['y'] for r in rows]); label = guarded.direction([r[name] for r in rows])
    avg = lambda x: float(np.average(x, weights=w))
    ratio = lambda mask,given: float(w[mask & given].sum()/w[given].sum()) if w[given].sum() else None
    recalls = [ratio(label==c,truth==c) for c in (-1,0,1)]
    return dict(n=len(rows), dates=len({r['origin'] for r in rows}),
        returnMae=avg(error), mape=avg(ape), p90ReturnError=legacy.quantile(error,w,.9),
        p90Mape=legacy.quantile(ape,w,.9), signedBias=avg(predicted-actual),
        directionAccuracy=avg(truth==label), alwaysUpAccuracy=avg(truth==1),
        downRecall=recalls[0], upRecall=recalls[2], flatRecall=recalls[1],
        balancedAccuracy=float(np.mean([x for x in recalls if x is not None])),
        downPrecision=ratio(truth==-1,label==-1),
        downFalsePositiveRate=ratio(label==-1,truth!=-1), downPrevalence=avg(truth==-1),
        downWarnings=int((label==-1).sum()), falseDownWarnings=int(((label==-1)&(truth!=-1)).sum()),
        confusion={str(t):{str(p):int(((truth==t)&(label==p)).sum()) for p in (-1,0,1)} for t in (-1,0,1)})


def macro_regimes(raw, origins):
    history = list(csv.DictReader(io.StringIO(raw.decode())))
    dates = [r['date'] for r in history]; prices = np.array([float(r['signalPrice']) for r in history])
    regimes = {}
    for origin in origins:
        prior = [i for i,d in enumerate(dates) if d < origin]
        if not prior or prior[-1] < 200: raise ValueError('Missing prior market history')
        i = prior[-1]; volatility = float(np.std(np.diff(np.log(prices[i-63:i+1])),ddof=1)*np.sqrt(252))
        regimes[origin] = dict(through=dates[i],volatility=volatility,
            name=('above200' if prices[i] >= prices[i-199:i+1].mean() else 'below200')+
                 ('HighVol' if volatility >= .2 else 'LowVol'))
    return regimes


def diagnostics(rows):
    w = legacy.weights(rows); w /= w.sum()
    fields = ('origin', 'stockRegime', 'marketRegime', 'truthLabel', 'errorBin')
    groups = {'all':np.ones(len(rows),dtype=bool)}
    for field in fields:
        for value in sorted({str(row[field]) for row in rows}):
            groups[field+':'+value] = np.array([str(row[field]) == value for row in rows])
    scores = {}; changes = {}; contributions = {f:{} for f in fields}
    for group,mask in groups.items():
        block = [r for r,keep in zip(rows,mask) if keep]
        scores[group] = {name:metrics(block,name,w[mask]) for name in METHODS+COMPONENTS}
        old = scores[group]['original']; new = scores[group]['regimeBlend']
        truth = guarded.direction([r['y'] for r in block])
        original = guarded.direction([r['original'] for r in block]); blend = guarded.direction([r['regimeBlend'] for r in block])
        delta = abs(np.expm1([r['regimeBlend'] for r in block])-np.expm1([r['y'] for r in block]))
        # Kept as an explicit second operation to make full-cohort contribution weights visible.
        delta = delta - abs(np.expm1([r['original'] for r in block])-np.expm1([r['y'] for r in block]))
        contribution = float(np.dot(w[mask],delta))
        changes[group] = dict(weightShare=float(w[mask].sum()), returnMaeChange=new['returnMae']-old['returnMae'],
            mapeChange=new['mape']-old['mape'],directionChange=new['directionAccuracy']-old['directionAccuracy'],
            additiveReturnMaeChange=contribution, directionFlips=int((original!=blend).sum()),
            correctToWrong=int(((original==truth)&(blend!=truth)).sum()),
            wrongToCorrect=int(((original!=truth)&(blend==truth)).sum()),
            weightedCorrectToWrong=float(w[mask][(original==truth)&(blend!=truth)].sum()),
            weightedWrongToCorrect=float(w[mask][(original!=truth)&(blend==truth)].sum()))
        if group != 'all':
            field,value = group.split(':',1); contributions[field][value] = contribution
    return scores,changes,contributions


def fingerprints(source, rows):
    return dict(keys=digest(canonical(sorted((r['symbol'],r['origin'],r['targetDate']) for r in rows))),
        outcomes=digest(canonical([{k:r[k] for k in ('symbol','origin','targetDate','y','pred','trend')} for r in rows])),
        sourceFolds=digest(canonical(source['folds'])))


def run(output):
    output = output.resolve()
    if HERE.resolve() not in output.parents: raise ValueError('Output must stay inside the isolated experiment')
    manifest,content = read_sources(); protocol = json.loads((HERE/'PROTOCOL.json').read_text())
    load = lambda name: json.loads(content['sources/'+name])
    snapshots = {}; rows_by_snapshot = {}; sources = {}
    for name,prefix,summary_name in [('pr53','pr53-','pr53-adaptive-summary.json.gz'),('latest','latest-','latest-summary.json.gz')]:
        source = load(prefix+'validation-126.json.gz'); saved = load(prefix+'adaptive-126.json.gz')['rows']; summary = load(summary_name)
        replayed = replay(source,saved,summary); sources[name] = source
        comparison = replayed['comparison']; start = comparison['evaluationStart']
        selection = legacy.matured([r for r in saved if r['origin'] < start],start)
        final = [r for r in saved if r['origin'] >= start]
        macro = macro_regimes(content['sources/spy-input.csv.gz'], sorted({r['origin'] for r in final}))
        enriched = []
        for row in final:
            original_ape = abs(np.expm1(row['original'])-np.expm1(row['y']))/np.exp(row['y'])
            enriched.append(dict(row, **replayed['components'][(row['symbol'],row['origin'])],
                stockRegime=legacy.regime(row),marketRegime=macro[row['origin']]['name'],
                truthLabel=int(guarded.direction(row['y'])),
                errorBin='<=10%' if original_ape <= .1 else '10-30%' if original_ape <= .3 else '>30%'))
        scores,changes,contributions = diagnostics(enriched)
        guarded_comparison = guarded.compare(saved)
        snapshots[name] = dict(sourceModel=source['model'],sourceGeneratedAt=source['generatedAt'],generatedAt=summary['generatedAt'],
            fullSourceRows=len(source['outcomes']), sourceDates=len(source['folds']),adapterRows=len(saved),
            adapterDates=len({r['origin'] for r in saved}), selectionN=len(selection),
            legacyComparison=comparison, guardedComparison=guarded_comparison,
            selectionScores={v:metrics(selection,v) for v in METHODS},
            selectionObjective={v:legacy.stats(selection,v)['mae']+.25*legacy.stats(selection,v)['p90'] for v in METHODS},
            replay=replayed['verification'], fingerprints=fingerprints(source,final), macroRegimes=macro,
            clocks=replayed['clocks'], scores=scores,pairedChanges=changes,contributions=contributions,
            blendMechanism=dict(averageWeights={b:float(np.average([r['blendWeights'][b] for r in enriched],weights=legacy.weights(enriched))) for b in legacy.BASES},
                averageBlendBias=float(np.average([r['blendBias'] for r in enriched],weights=legacy.weights(enriched))),
                localFits=sum(r['localFit'] for r in enriched),rows=len(enriched)))
        rows_by_snapshot[name] = enriched
    prior_report = load('pr53-output-results.json.gz')
    for method in METHODS:
        for metric in ('mape','returnMae','p90Mape','p90ReturnError','directionAccuracy','downRecall'):
            if not equivalent(snapshots['pr53']['scores']['all'][method][metric],prior_report['scores']['all'][method][metric]):
                raise ValueError('PR53 fixed research results do not match replay: '+method+'/'+metric)
    if prior_report['selectedCandidate'] is not None:
        raise ValueError('Unexpected selected candidate in frozen PR53 results')
    old = rows_by_snapshot['pr53']; new = rows_by_snapshot['latest']
    key = lambda row:(row['symbol'],row['origin'],row['targetDate'])
    shared = set(map(key,old)) & set(map(key,new))
    old_dates = sorted({r['origin'] for r in old}); new_dates = sorted({r['origin'] for r in new})
    alignment = []
    for previous,current in zip(old_dates,new_dates):
        a = {r['symbol']:r for r in old if r['origin'] == previous}; b = {r['symbol']:r for r in new if r['origin'] == current}
        symbols = sorted(a.keys() & b.keys())
        alignment.append(dict(pr53Origin=previous, latestOrigin=current, pr53N=len(a),latestN=len(b),
            commonSymbols=len(symbols),onlyPR53=sorted(a.keys()-b.keys()),onlyLatest=sorted(b.keys()-a.keys()),
            changedTargetDates=sum(a[s]['targetDate'] != b[s]['targetDate'] for s in symbols),
            changedOutcomes=sum(a[s]['y'] != b[s]['y'] for s in symbols),
            changedOriginalPredictions=sum(a[s]['original'] != b[s]['original'] for s in symbols)))
    pit = load('pr25-pit-audit.json.gz'); lifecycle = load('pr25-lifecycle-audit.json.gz')
    status = load('latest-status.json.gz'); registry = load('latest-registry.json.gz')
    summary = load('latest-summary.json.gz')
    for horizon in ('126','252'):
        reference = summary['horizons'][horizon]['comparison']; public = status['forecastResearch']['horizons'][horizon]
        for field in ('passed','checks','improvementVsOriginal'):
            if public.get(field) != reference.get(field): raise ValueError('Status and research summary disagree')
    if status['forecastResearch']['generatedAt'] != summary['generatedAt']: raise ValueError('Status research clock mismatch')
    if registry['events'] or any(m.startswith('completed-error-adapter-v1:') for m in registry['champions'].values()):
        raise ValueError('Unexpected production model promotion in frozen registry')
    source_252 = load('latest-validation-252.json.gz'); adapter_252 = load('latest-adaptive-252.json.gz')
    report = dict(version=protocol['version'],evidenceClass='quarantined-retrospective-diagnostic',
        manifestSha256=digest((HERE/'input-manifest.json').read_bytes()),protocolSha256=digest((HERE/'PROTOCOL.json').read_bytes()),
        implementationSha256={path:digest((ROOT/path).read_bytes()) for path in ('scripts/build_adaptive_research.py','scripts/build_decision_support.py','assets/decision-support.js')},
        python=sys.version.split()[0],numpy=np.__version__,snapshots=snapshots,
        pr53FixedResearchResultsMatch=True,pr53SelectedCandidate=prior_report['selectedCandidate'],
        snapshotComparison=dict(sameModelID=sources['pr53']['model'] == sources['latest']['model'],
            sameProducerBytes=content['reuse/build_adaptive_research.py'] == content['reuse/latest_build_adaptive_research.py'],
            sameBaseModelCode=content['reuse/build_learned_forecasts.py'] == content['reuse/pr53_build_learned_forecasts.py'],
            sameSampleSize=len(old) == len(new), samePopulation=shared == set(map(key,old)) == set(map(key,new)),
            commonExactKeys=len(shared),alignment=alignment,
            samplingCause='build_learned_forecasts.py computes origin indices backwards from len(calendar)-h-2; one new SPY session shifts every test origin. Source models are refit at the shifted clocks; model ID does not freeze estimates.'),
        sourceIntegrityVsReadiness=dict(byteIntegrityVerified=True,pitReady=pit['readyOriginCount'],pitOrigins=pit['originCount'],
            lifecycleReady=lifecycle['readyOriginCount'],latestOriginsPitEvidenceReady=0,
            modelTrainingAllowed=pit['modelTrainingAllowed'],productionChangesAllowed=pit['productionChangesAllowed'],
            missing=['historical membership/sector coverage','permanent security identity/dated aliases',
                     'original publication/revision and price vintages','removed/delisted full-cohort outcomes','settled merger/shareholder lifecycle outcomes']),
        productionBoundary=dict(frozenStatusPassed=False,usedForTrading=status['forecastResearch']['usedForTrading'],
            liveForecastChanged=status['forecastResearch']['horizons']['126']['liveForecastChanged'],
            champions=registry['champions'],promotionEvents=len(registry['events']),
            existingGap='Before this PR, paired_gate never checked adapter eligible:false or PIT completeness. It could automatically promote on twelve good disjoint price blocks and a fresh interval, regardless of historical failure or direction.',
            correction='Quarantine adapter namespace at paired_gate; stop pre-existing quarantined champions before any writes. Keep collection/scoring enabled; no production eligibility override is accepted.'),
        horizon252=dict(status=summary['horizons']['252']['comparison']['status'],
            sourceRows=len(source_252['outcomes']),sourceDates=len(source_252['folds']),adapterRows=len(adapter_252['rows']),
            maturedPriorDatesByOrigin={d:len({r['origin'] for r in legacy.matured(legacy.normalize(source_252),d)}) for d in sorted({r['origin'] for r in source_252['outcomes']})},
            requiredMaturedPriorDates=legacy.MIN_DATES,
            reason='Five source folds leave at most three strictly matured earlier blocks at any historical origin; four are required before the first adapter prediction.'),
        selectedCandidate=None,productionEligible=False,productionChanged=False,top3Changed=False,tradingChanged=False,
        notNewHoldout=True,independentEvaluationDates=4)
    output.mkdir(parents=True,exist_ok=True)
    (output/'results.json').write_bytes(canonical(report))
    (output/'paired-predictions.json.gz').write_bytes(gzip.compress(canonical(rows_by_snapshot),mtime=0))
    table = []
    for snapshot,value in snapshots.items():
        for group,methods in value['scores'].items():
            for method,score in methods.items():
                table.append(dict(snapshot=snapshot,group=group,method=method,**{k:v for k,v in score.items() if not isinstance(v,dict)}))
    with (output/'metrics.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=sorted({k for row in table for k in row}),lineterminator='\n')
        writer.writeheader();writer.writerows(table)
    hashes = {name:digest((output/name).read_bytes()) for name in ('results.json','paired-predictions.json.gz','metrics.csv')}
    (output/'verification.json').write_bytes(canonical(dict(outputHashes=hashes,sourceHashesVerified=True,
        bothSnapshotReplays=True,exactKeyIntersection=len(shared),fullCohorts=True,noProductionWrites=True)))
    print(json.dumps(dict(latest=snapshots['latest']['scores']['all']['regimeBlend'],
        selectedCandidate=report['selectedCandidate'],exactSharedKeys=len(shared)),ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=HERE/'output')
    run(parser.parse_args().output)
