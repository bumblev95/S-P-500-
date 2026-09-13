"""Finite, preregistered price experiment; no production mutation or later tuning."""
import os
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
import argparse
import gzip
import hashlib
import json
import platform
import warnings
from datetime import datetime, timezone
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import HuberRegressor, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from build_learned_forecasts import FEATURES, PARAMS, feature_frame, trend, qualifies
from build_forecasts import atomic_json
from research_universe import load_universe

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path('research/experiments/price-gate-2026-09-13')
MODEL = 'price-gate-study-v1'
CONTROLS = ('noChange', 'trend', 'mainLongHistory')
CHALLENGERS = ('freshLog','freshMedian','freshMape','recentMedian','ownMedian',
              'ownMape','robustLinear','marketResidual','marketState',
              'linearResidual','equalBlend','recentBlend')
NAMES = CONTROLS + CHALLENGERS
OWN = [f for f in FEATURES if f not in ('market21','market63','relative63')]
RANKED = OWN + ['rank_'+f for f in OWN]
EVAL_START = '2019-01-01'
ARCHIVE_SHA = '5bf33128f82381c31ac97563aac099d22d1242febea44b0dee30e4ddda04662c'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def weight(dates):
    _, inv, counts = np.unique(dates, return_inverse=True, return_counts=True)
    w = 1. / counts[inv]
    return w / w.mean()


def direction(gross):
    return np.where(gross > 1.02, 1, np.where(gross < .98, -1, 0))


def read_frames(root, through='9999-12-31'):
    raw = {}; hashes = {}; lengths = {}
    for p in sorted((root/'research/history/audit').glob('*.json')):
        doc = json.loads(p.read_text())
        lengths[doc['symbol']] = len(doc['prices'])
        raw[doc['symbol']] = [q for q in doc['prices'] if q['date'] <= through]
        hashes[doc['symbol']] = sha(p)
    universe = load_universe(root)
    representatives = {}; missing = []
    for s, v in sorted(universe['members'].items()):
        if s in raw and lengths[s] >= 600:
            representatives.setdefault(v['cik'], s)
        else:
            missing.append(s)
    symbols = sorted(representatives.values())
    frames = {s:feature_frame(raw[s]) for s in ['SPY'] + symbols}
    market = frames['SPY']
    sp = pd.Series({q['date']:q['close'] for q in raw['SPY']}).sort_index()
    mr = sp.pct_change(fill_method=None)
    for s, f in frames.items():
        f['market21'] = market.r21.reindex(f.index)
        f['market63'] = market.r63.reindex(f.index)
        f['relative63'] = f.r63-f.market63
        prices = pd.Series({q['date']:q['close'] for q in raw[s]}).sort_index()
        rr = prices.pct_change(fill_method=None)
        pair = pd.concat([rr.rename('stock'),mr.rename('market')],axis=1).reindex(prices.index)
        cov = pair.stock.rolling(252,min_periods=200).cov(pair.market)
        var = pair.market.rolling(252,min_periods=200).var()
        f['beta'] = (.5+.5*cov/var).clip(-.5,2.5).reindex(f.index)
    provenance = dict(historyHashes=hashes,universeHash=sha(root/'research/universe.json'),
        sourceArchiveSha256=ARCHIVE_SHA,sourceAsOf=str(sp.index[-1]),
        selectedSymbols=symbols,targetIssuers=universe['issuerCount'],priceIssuers=len(symbols),
        missingTickers=missing,shareClassRule='First alphabetically available ticker per CIK',
        priceBasis='Yahoo quote Close: split adjusted, cash dividends excluded',
        quoteFirstDate=str(sp.index[0]),quoteLastDate=str(sp.index[-1]))
    return frames, sp, provenance


def make_panel(frames, sp, h, extra_origins=()):
    calendar = list(frames['SPY'].index)
    anchor = int(np.searchsorted(calendar, '2014-01-01'))
    monthly = set(calendar[anchor % 21::21])
    primary = [calendar[j] for j in range(anchor % h,len(calendar)-h,h)
               if calendar[j] >= '2011-01-01']
    current = calendar[-1]
    keep = monthly | set(primary) | set(extra_origins) | {current}
    chunks = []
    for symbol, frame in frames.items():
        f = frame.copy()
        f['origin'] = f.index
        f['targetDate'] = pd.Series(f.index,index=f.index).shift(-h)
        f['y'] = np.log(f.close.shift(-h)/f.close)
        f['symbol'] = symbol
        f['trend'] = trend(f,h)
        f['scale'] = np.maximum(.03,f.vol84*np.sqrt(h/252))
        f = f[f.index.isin(keep)].copy()
        f['marketY'] = np.log(f.targetDate.map(sp)/f.origin.map(sp))
        chunks.append(f)
    panel = pd.concat(chunks,ignore_index=True).replace([np.inf,-np.inf],np.nan)
    panel = panel.dropna(subset=FEATURES+['beta','scale'])
    stock = panel.symbol!='SPY'
    ranked = panel.loc[stock,OWN].groupby(panel.loc[stock,'origin']).rank(pct=True)*2-1
    for f in OWN:
        panel.loc[stock,'rank_'+f] = ranked[f]
    panel = panel.sort_values(['origin','symbol']).reset_index(drop=True)
    assert not panel.duplicated(['symbol','origin']).any()
    return panel, calendar, monthly, primary


def hgb(train, columns, target, weights=None, loss='absolute_error'):
    return HistGradientBoostingRegressor(**PARAMS,loss=loss).fit(
        train[columns],target,sample_weight=weights)


def fit_all(panel, calendar, monthly, origin, h):
    mature = (panel.targetDate < origin) & (panel.origin < origin) & panel.origin.isin(monthly)
    train = panel[mature & (panel.symbol!='SPY')].dropna(subset=['y','marketY']+RANKED)
    if len(train)<3000:
        raise ValueError(f'Insufficient training {origin}: {len(train)}')
    assert train.targetDate.max()<origin
    w = weight(train.origin)
    gross = np.exp(train.y)
    cut = calendar[max(0,calendar.index(origin)-h-126)]
    old = train[(train.targetDate<cut)&(train.origin<cut)]
    if len(old)<500:
        raise ValueError(f'Insufficient main-control training {origin}: {len(old)}')
    recent_start = str(int(origin[:4])-6)+origin[4:]
    recent = train[train.origin>=recent_start]
    m = {
        'mainLongHistory':hgb(old,FEATURES,old.y,loss='squared_error'),
        'freshLog':hgb(train,FEATURES,train.y,w,loss='squared_error'),
        'freshMedian':hgb(train,FEATURES,gross,w),
        'freshMape':hgb(train,FEATURES,gross,w/gross),
        'recentMedian':hgb(recent,FEATURES,np.exp(recent.y),weight(recent.origin)),
        'ownMedian':hgb(train,OWN,gross,w),
        'ownMape':hgb(train,OWN,gross,w/gross),
    }
    linear = make_pipeline(StandardScaler(),HuberRegressor(epsilon=1.35,alpha=10,max_iter=500))
    with warnings.catch_warnings(record=True) as caught:
        linear.fit(train[FEATURES],train.y,huberregressor__sample_weight=w)
    if caught:
        raise ValueError('Robust linear fitting warning: '+str(caught[0].message))
    m['robustLinear'] = linear
    residual = train.y-train.beta*train.marketY
    m['residualTree'] = hgb(train,RANKED,residual,w)
    m['residualLinear'] = make_pipeline(StandardScaler(),Ridge(alpha=100)).fit(
        train[RANKED],residual,ridge__sample_weight=w)
    market = panel[mature & (panel.symbol=='SPY')].dropna(subset=['y'])
    market = market[market.origin>=str(int(origin[:4])-10)+origin[4:]]
    assert not market.origin.duplicated().any() and market.targetDate.max()<origin
    m['marketMedian'] = float(np.median(market.y))
    m['marketRidge'] = make_pipeline(StandardScaler(),Ridge(alpha=100)).fit(market[OWN],market.y)
    meta = dict(origin=origin,trainRows=len(train),trainDates=int(train.origin.nunique()),
        trainTargetThrough=str(train.targetDate.max()),mainTrainTargetThrough=str(old.targetDate.max()),
        mainTrainCutoff=cut,mainTrainRows=len(old),recentFirstOrigin=str(recent.origin.min()),
        marketTrainRows=len(market),marketTrainTargetThrough=str(market.targetDate.max()))
    return m,meta


def predict_all(m, test, market):
    out = dict(noChange=np.ones(len(test)),trend=np.exp(test.trend.to_numpy()))
    for n in ('mainLongHistory','freshLog'):
        out[n] = np.exp(m[n].predict(test[FEATURES]))
    for n in ('freshMedian','freshMape','recentMedian'):
        out[n] = m[n].predict(test[FEATURES])
    for n in ('ownMedian','ownMape'):
        out[n] = m[n].predict(test[OWN])
    out['robustLinear'] = np.exp(m['robustLinear'].predict(test[FEATURES]))
    residual = .5*m['residualTree'].predict(test[RANKED])
    base = test.beta.to_numpy()*m['marketMedian']
    state = .5*m['marketMedian']+.5*float(m['marketRidge'].predict(market[OWN])[0])
    out['marketResidual'] = np.exp(base+residual)
    out['marketState'] = np.exp(test.beta.to_numpy()*state+residual)
    out['linearResidual'] = np.exp(base+.5*m['residualLinear'].predict(test[RANKED]))
    out['equalBlend'] = sum(out[n] for n in ('freshMedian','marketResidual','robustLinear'))/3
    out['recentBlend'] = sum(out[n] for n in ('freshMedian','recentMedian','marketState'))/3
    if set(out)!=set(NAMES) or any(not np.all(np.isfinite(p)&(p>0)) for p in out.values()):
        raise ValueError('Invalid candidate output; do not clip or drop')
    return out


def quantile(x,w,q):
    ix = np.argsort(x,kind='stable')
    return float(np.asarray(x)[ix][np.searchsorted(np.cumsum(w[ix]),q*w.sum(),side='left')])


def calibrate(prior,origin):
    if not prior:
        return {}
    d = pd.DataFrame(prior)
    ends = d.groupby('origin').targetDate.max()
    dates = list(ends[ends<origin].index)[-12:]
    if len(dates)<3:
        return {}
    d = d[d.origin.isin(dates)]
    w = weight(d.origin)
    bands = {}
    for n in NAMES:
        error = (np.log(d.actual)-np.log(d[n]))/d.scale
        bands[n] = dict(low=min(0.,quantile(error.to_numpy(),w,.1)),
            high=max(0.,quantile(error.to_numpy(),w,.9)),dates=len(dates),
            targetThrough=str(d.targetDate.max()))
    return bands


def stats(rows,name):
    d = pd.DataFrame(rows)
    if d.empty:
        return dict(n=0,dates=0)
    actual = d.actual.to_numpy(); pred = d[name].to_numpy()
    error = abs(pred/actual-1); mae = abs(pred-actual); logerror = abs(np.log(pred/actual))
    ad = direction(actual); pdirection = direction(pred)
    down = ad==-1; predicted_down = pdirection==-1
    by = {}
    for origin, ix in d.groupby('origin').indices.items():
        by[origin] = dict(mape=float(error[ix].mean()),mae=float(mae[ix].mean()),
            logMae=float(logerror[ix].mean()),n=len(ix))
    interval = [(i,r.get('bands',{}).get(name)) for i,r in enumerate(rows)]
    interval = [(i,b) for i,b in interval if b]
    covered = [np.log(pred[i])+b['low']*rows[i]['scale']<=np.log(actual[i])<=
               np.log(pred[i])+b['high']*rows[i]['scale'] for i,b in interval]
    out = dict(n=len(d),dates=len(by),mae=float(mae.mean()),mape=float(error.mean()),
        dateMeanMape=float(np.mean([v['mape'] for v in by.values()])),
        dateMeanLogMae=float(np.mean([v['logMae'] for v in by.values()])),
        p90=float(np.quantile(error,.9)),within10=float(np.mean(error<=.1)),
        noChangeMae=float(np.mean(abs(actual-1))),trendMae=float(np.mean(abs(actual-d.trend))),
        directionAccuracy=float(np.mean(ad==pdirection)),alwaysUpAccuracy=float(np.mean(ad==1)),
        actualDownCount=int(down.sum()),predictedDownCount=int(predicted_down.sum()),
        downRecall=float(predicted_down[down].mean()) if down.any() else None,
        downPrecision=float(down[predicted_down].mean()) if predicted_down.any() else None,
        downPrevalence=float(down.mean()),rangeCoverage=float(np.mean(covered)) if covered else 0.,
        rangeRows=len(interval),rangeDates=len({rows[i]['origin'] for i,b in interval}),
        byDate=by,firstDate=str(d.origin.min()),lastDate=str(d.origin.max()))
    # Missing intervals must not disappear from an apparent gate pass.
    out['productionPassed'] = bool(qualifies(out) and len(interval)==len(d))
    return out


def select(rows):
    earlier = [r for r in rows if '2014-01-01'<=r['origin']<EVAL_START and r['targetDate']<EVAL_START]
    scores = {n:stats(earlier,n) for n in NAMES}
    eligible = [n for n in CHALLENGERS if scores[n]['mae']<.98*min(scores[n]['noChangeMae'],scores[n]['trendMae'])
        and scores[n]['directionAccuracy']>scores[n]['alwaysUpAccuracy']
        and (scores[n]['downRecall'] or 0)>=.1]
    chosen = min(eligible or CHALLENGERS,key=lambda n:scores[n]['dateMeanMape']+.25*scores[n]['p90'])
    return dict(chosen=chosen,provisional=not bool(eligible),screened=eligible,metrics=scores,
        dates=sorted({r['origin'] for r in earlier}),targetThrough=max(r['targetDate'] for r in earlier))


def gates(rows,name,baseline=CONTROLS):
    scores = {n:stats(rows,n) for n in set(baseline+(name,))}
    m = scores[name]
    rng = np.random.default_rng(17)
    dates = sorted(m['byDate']);draws = rng.integers(0,len(dates),size=(5000,len(dates)))
    intervals = {}
    for b in baseline:
        diff = np.array([m['byDate'][d]['mape']-scores[b]['byDate'][d]['mape'] for d in dates])
        bootstrap = diff[draws].mean(axis=1)
        intervals[b] = dict(difference=float(diff.mean()),lower=float(np.quantile(bootstrap,.025)),
                            upper=float(np.quantile(bootstrap,.975)))
    wins = float(np.mean([m['byDate'][d]['mape']<min(scores[b]['byDate'][d]['mape'] for b in baseline) for d in dates]))
    main_checks = dict(enoughDates=m['dates']>=4,
        returnError=m['mae']<.98*min(m['noChangeMae'],m['trendMae']),
        direction=m['directionAccuracy']>m['alwaysUpAccuracy'],
        downRecall=m['actualDownCount']<20 or (m['downRecall'] or 0)>=.1,
        coverage=m['rangeRows']==m['n'] and m['rangeCoverage']>=.60)
    checks = dict(enoughDates=m['dates']>=6,
        priceError=m['dateMeanMape']<.98*min(scores[b]['dateMeanMape'] for b in baseline),
        tail=m['p90']<=min(scores[b]['p90'] for b in baseline),consistency=wins>=.60,
        downPrecision=(m['downPrecision'] or 0)>=m['downPrevalence'],
        uncertainty=all(q['upper']<0 for q in intervals.values()))
    env_b = ('noChange','mainLongHistory')
    env = dict(enoughDates=m['dates']>=6,
        logError=m['dateMeanLogMae']<.95*min(scores[b]['dateMeanLogMae'] for b in env_b),
        priceError=m['dateMeanMape']<=min(scores[b]['dateMeanMape'] for b in env_b),
        tail=m['p90']<=min(scores[b]['p90'] for b in env_b),
        consistency=float(np.mean([m['byDate'][d]['mape']<min(scores[b]['byDate'][d]['mape'] for b in env_b) for d in dates]))>=.6,
        direction=m['directionAccuracy']>max(m['alwaysUpAccuracy'],*(scores[b]['directionAccuracy'] for b in env_b)),
        downRecall=(m['downRecall'] or 0)>=.1)
    assert all(main_checks.values())==m['productionPassed']
    return dict(mainChecks=main_checks,mainPassed=m['productionPassed'],priceChecks=checks,
        pricePassed=all(checks.values()),environmentChecks=env,environmentPassed=all(env.values()),
        historicalPassed=m['productionPassed'] and all(checks.values()),dateWinRate=wins,
        priceDifferenceIntervals=intervals,atMost10Percent=m['dateMeanMape']<=.10,
        atMost5Percent=m['dateMeanMape']<=.05)


def archive_compare(root,panel,archive_rows):
    matched = []; mismatches = []; missing = []
    lookup = {(r['symbol'],r['origin']):r for r in archive_rows}
    for r in panel:
        old = lookup.get((r['symbol'],r['origin']))
        if old is None:
            continue
        if old['targetDate']!=r['targetDate'] or abs(np.log(r['actual'])-old['y'])>1e-10:
            mismatches.append([r['symbol'],r['origin'],old['targetDate'],r['targetDate']])
            continue
        row = dict(r,publishedMain=float(np.exp(old['pred'])))
        row['bands'] = dict(r.get('bands',{}),publishedMain=dict(
            low=(old['low']-old['pred'])/r['scale'],high=(old['high']-old['pred'])/r['scale']))
        matched.append(row)
    keys = {(r['symbol'],r['origin']) for r in matched}
    missing = [dict(symbol=r['symbol'],origin=r['origin']) for r in archive_rows if (r['symbol'],r['origin']) not in keys]
    if mismatches:
        raise ValueError('Archived target mismatch: '+str(mismatches[:4]))
    return matched,dict(archivedRows=len(archive_rows),matchedRows=len(matched),
        unmatchedRows=len(missing),unmatched=missing,targetMismatches=mismatches,
        explanation='One representative per issuer; ETFs, second share classes and missing raw histories excluded identically for every candidate.')


def write_gzip(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('wb') as stream:
        with gzip.GzipFile(filename='',mode='wb',fileobj=stream,mtime=0) as zipped:
            zipped.write(json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode())


def build(root=ROOT):
    folder = root/FOLDER
    frames,sp,provenance = read_frames(root)
    provenance.update(protocolHash=sha(folder/'PROTOCOL.md'),sourceCodeHash=sha(Path(__file__)),
        productionCodeHash=sha(root/'scripts/build_learned_forecasts.py'),
        versions=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,sklearn=sklearn.__version__))
    output = dict(schemaVersion=1,model=MODEL,status='running',generatedAt=datetime.now(timezone.utc).isoformat(),
        provenance=provenance,candidateCount=len(CHALLENGERS),configurationCount=2*len(CHALLENGERS),
        controls=list(CONTROLS),horizons={},productionPromoted=False,
        limitations=['Previously explored history; not an untouched holdout.',
            'Current-constituent survivorship bias; no delisted stocks.',
            'Revised public quote history; not a certified point-in-time vintage.',
            'Date-block intervals are descriptive; few correlated market periods.',
            'Historical passing does not establish future 5–10% price accuracy.'])
    issued = dict(model=MODEL,issuedAt=datetime.now(timezone.utc).isoformat(),asOf=str(sp.index[-1]),
        provenance=provenance,productionEligible=False,horizons={})
    for h in (126,252):
        source = root/f'ml/validation/{h}.json'
        archive = json.loads(source.read_text())['outcomes']
        archive_origins = sorted({r['origin'] for r in archive})
        panel,calendar,monthly,primary = make_panel(frames,sp,h,archive_origins)
        following = dict(zip(primary,primary[1:]))
        origins = sorted(set(primary)|set(archive_origins))
        primary_rows = []; secondary = []; folds = []; choice = None
        replay_origin = next(d for d in primary if d>='2023-01-01')
        for origin in origins:
            if origin>=EVAL_START and choice is None:
                choice = select(primary_rows)
                atomic_json(folder/f'{h}-selection.json',choice)
                print('SELECTION FROZEN',h,choice['chosen'],'provisional',choice['provisional'],flush=True)
            test = panel[(panel.origin==origin)&(panel.symbol!='SPY')].dropna(subset=['y','marketY']+RANKED)
            if origin in primary and origin in following:
                test = test[test.targetDate<=following[origin]]
            market = panel[(panel.symbol=='SPY')&(panel.origin==origin)]
            models,meta = fit_all(panel,calendar,monthly,origin,h)
            point = predict_all(models,test,market)
            bands = calibrate(primary_rows,origin)
            rows = []
            for i,r in enumerate(test.to_dict('records')):
                rows.append(dict(symbol=r['symbol'],origin=origin,targetDate=r['targetDate'],
                    actual=float(np.exp(r['y'])),scale=float(r['scale']),anchor=float(r['close']),
                    bands=bands,**{n:float(point[n][i]) for n in NAMES}))
            if origin in primary:
                primary_rows.extend(rows)
            if origin in archive_origins:
                secondary.extend(rows)
            folds.append(dict(meta,primary=origin in primary,rows=len(rows),
                calibrationTargetThrough=next(iter(bands.values()))['targetThrough'] if bands else None))
            if origin==replay_origin:
                atomic_json(folder/f'{h}-replay-reference.json',dict(origin=origin,
                    predictions=[dict(symbol=r['symbol'],**{n:r[n] for n in NAMES}) for r in rows]))
            print('FOLD',h,origin,len(rows),'train',meta['trainRows'],flush=True)
        if choice is None:
            raise ValueError('Evaluation did not run')
        evaluation = [r for r in primary_rows if r['origin']>=EVAL_START]
        score = {n:stats(evaluation,n) for n in NAMES}
        checks = {n:gates(evaluation,n) for n in CHALLENGERS}
        matched,audit = archive_compare(root,secondary,archive)
        audit['sourceHash'] = sha(source)
        archived_scores = {n:stats(matched,n) for n in NAMES+('publishedMain',)}
        selected = choice['chosen']
        own_pass = [s for s in sorted({r['symbol'] for r in evaluation})
                    if stats([r for r in evaluation if r['symbol']==s],selected)['productionPassed']]
        result = dict(selected=selected,selectionProvisional=choice['provisional'],selection=choice,
            evaluation=score,candidateGates=checks,selectedGate=checks[selected],
            archivedComparison=dict(audit=audit,metrics=archived_scores),folds=folds,
            individuallyPassingSymbols=own_pass,primaryDates=sorted({r['origin'] for r in evaluation}),
            replayOrigin=replay_origin,productionPromoted=False)
        output['horizons'][str(h)] = result
        write_gzip(folder/f'{h}-outcomes.json.gz',dict(model=MODEL,primary=primary_rows,archived=matched))
        atomic_json(folder/f'{h}-results.json',result)
        current = calendar[-1]
        live = panel[(panel.origin==current)&(panel.symbol!='SPY')].dropna(subset=RANKED)
        m,meta = fit_all(panel,calendar,monthly,current,h)
        p = predict_all(m,live,panel[(panel.origin==current)&(panel.symbol=='SPY')])[selected]
        bands = calibrate(primary_rows,current)[selected]
        issued['horizons'][str(h)] = dict(selected=selected,training=meta,bands=bands,
            stocks={r.symbol:dict(anchor=float(r.close),base=float(r.close*p[i]),
                low=float(r.close*p[i]*np.exp(bands['low']*r.scale)),
                high=float(r.close*p[i]*np.exp(bands['high']*r.scale)),
                grossReturn=float(p[i]),origin=current,horizon=h) for i,r in enumerate(live.itertuples())})
        (root/'ml/models/price-gate-study').mkdir(parents=True,exist_ok=True)
        joblib.dump(m,root/f'ml/models/price-gate-study/{h}.joblib')
        print('RESULT',h,selected,json.dumps(checks[selected]),flush=True)
    output['status'] = 'completed'
    output['completedAt'] = datetime.now(timezone.utc).isoformat()
    atomic_json(folder/'results.json',output)
    issued['issuedAt'] = output['completedAt']
    if (folder/'issued.json').exists():
        raise ValueError('First-issued record already exists; refusing overwrite')
    atomic_json(folder/'issued.json',issued)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args()
    build(args.root)
