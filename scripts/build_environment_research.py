"""Fixed public-data challenger experiment; no trade records, no automatic promotion."""
import os
os.environ.setdefault('OMP_NUM_THREADS','2')
import json, math, hashlib, time
from collections import Counter, defaultdict
from bisect import bisect_left
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from build_forecasts import atomic_json
from research_universe import load_universe
from build_research_inputs import stock_before, crypto_before, STOCK_FIELDS, CRYPTO_FIELDS
from build_earnings_inputs import earnings_before, FIELDS as EARNINGS_FIELDS
ROOT=Path(__file__).resolve().parents[1]
STOCKS=('NVDA','AMD','AVGO','MU','AMAT','QCOM','INTC','MSFT','AAPL','GOOGL','AMZN','META','TSLA','JPM','XOM','SPY')
PROXIES={'SPY':'미국 주식','QQQ':'기술주','HYG':'하이일드 채권 가격','IEF':'중기 국채 가격','UUP':'달러 ETF','^VIX':'VIX'}
BASE=['return7','return30','return90','return180','vol30','vol90','distance20','distance50','distance200','drawdown90']
CONTEXT=[f'{s}_{k}' for s in PROXIES for k in ('return30','vol30','distance200')]+['BTC_return30','BTC_vol30','BTC_distance200']
NAMES=('noChange','priceOnly','environment','ensemble','balanced')
MODEL='environment-challenger-v5-horizon-specific'

# Predeclared before the later holdout is evaluated. Each stock horizon gets
# independent inputs, capacity and a balanced direction classifier.
HORIZON_PROFILES={
    21:dict(name='short-21d',field='z',max_iter=70,max_leaf_nodes=15,min_samples_leaf=35,
            l2_regularization=12.,learning_rate=.04,class_weight_power=.45,
            direction_probability=.46,direction_margin=.04),
    84:dict(name='medium-84d',field='w',max_iter=85,max_leaf_nodes=11,min_samples_leaf=45,
            l2_regularization=15.,learning_rate=.04,class_weight_power=.55,
            direction_probability=.44,direction_margin=.03),
    252:dict(name='long-252d',field='w',max_iter=100,max_leaf_nodes=7,min_samples_leaf=60,
             l2_regularization=20.,learning_rate=.035,class_weight_power=.65,
             direction_probability=.42,direction_margin=.02),
}

def direction_label(value):
    return 1 if value>1.02 else -1 if value<.98 else 0

class HorizonModel:
    """Independent return and balanced-direction estimators for one horizon."""
    def __init__(self,horizon):
        self.horizon=horizon;self.profile=HORIZON_PROFILES[horizon]
        p=self.profile
        common=dict(max_iter=p['max_iter'],max_leaf_nodes=p['max_leaf_nodes'],
                    min_samples_leaf=p['min_samples_leaf'],l2_regularization=p['l2_regularization'],
                    learning_rate=p['learning_rate'],early_stopping=False,random_state=23+horizon)
        self.return_model=HistGradientBoostingRegressor(loss='absolute_error',**common)
        self.direction_model=HistGradientBoostingClassifier(loss='log_loss',**common)

    def matrix(self,rows):
        field=self.profile['field']
        # Continuous context plus explicit bear/high-volatility regime flags.
        return np.asarray([r[field]+[float(r['regime'].startswith('하락')),
                                      float('고변동' in r['regime'])] for r in rows],dtype=float)

    def fit(self,rows):
        x=self.matrix(rows);y=np.asarray([math.log(r['y']) for r in rows]);labels=np.asarray([direction_label(r['y']) for r in rows])
        counts=Counter(labels);power=self.profile['class_weight_power']
        weights=np.asarray([(len(labels)/(len(counts)*counts[label]))**power for label in labels])
        self.return_model.fit(x,y)
        self.direction_model.fit(x,labels,sample_weight=weights)
        return self

    def predict(self,rows):
        x=self.matrix(rows);logs=self.return_model.predict(x);probability=self.direction_model.predict_proba(x)
        columns={int(label):i for i,label in enumerate(self.direction_model.classes_)};result=[];details=[]
        threshold=self.profile['direction_probability'];margin=self.profile['direction_margin']
        for raw,prob in zip(logs,probability):
            p={label:float(prob[columns[label]]) if label in columns else 0. for label in (-1,0,1)}
            if p[-1]>=threshold and p[-1]>=p[1]+margin:value=min(float(raw),math.log(.975));chosen=-1
            elif p[1]>=threshold and p[1]>=p[-1]+margin:value=max(float(raw),math.log(1.025));chosen=1
            else:value=float(np.clip(raw,math.log(.98),math.log(1.02)));chosen=0
            result.append(math.exp(value));details.append(dict(down=p[-1],flat=p[0],up=p[1],chosen=chosen))
        return np.asarray(result),details

def fit_horizon(train,horizon):
    return HorizonModel(horizon).fit(train)
def fetch_history(symbol,folder,today):
    path=folder/(symbol.replace('^','INDEX_')+'.json')
    old=json.loads(path.read_text()) if path.exists() else {}
    if old.get('checkedDate')==today:return old['prices']
    ticker=symbol.replace('.', '-')
    u='https://query1.finance.yahoo.com/v8/finance/chart/'+ticker+'?range=20y&interval=1d'
    with urlopen(Request(u,headers={'User-Agent':'DashboardEnvironmentResearch/1.0'}),timeout=25) as r:d=json.load(r)
    q=d['chart']['result'][0]
    if q['meta']['symbol'].upper()!=ticker.upper():raise ValueError('Asset identity mismatch')
    close=q['indicators'].get('adjclose',[{}])[0].get('adjclose',q['indicators']['quote'][0]['close'])
    rows=[]
    for t,p in zip(q['timestamp'],close):
        day=datetime.fromtimestamp(t,timezone.utc).date().isoformat()
        if day<today and p is not None and math.isfinite(p) and p>0:rows.append({'date':day,'close':float(p)})
    atomic_json(path,{'symbol':symbol,'source':'Yahoo adjusted daily close','checkedDate':today,'prices':rows})
    return rows

def features(rows,annual_days=252):
    if len(rows)<200:return {}
    p=np.array([r['close'] for r in rows],dtype=float);logret=np.diff(np.log(p))
    from numpy.lib.stride_tricks import sliding_window_view
    i=np.arange(199,len(p));columns=[np.log(p[i]/p[i-n]) for n in (7,30,90,180)]
    columns += [sliding_window_view(logret,n).std(axis=1,ddof=1)[i-n]*np.sqrt(annual_days) for n in (30,90)]
    columns += [p[i]/sliding_window_view(p,n).mean(axis=1)[i-n+1]-1 for n in (20,50,200)]
    columns += [p[i]/sliding_window_view(p,90).max(axis=1)[i-89]-1]
    return {rows[j]['date']:x for j,x in zip(i,np.column_stack(columns).tolist())}

def context_before(series,day,max_age=5):
    # Every context close must precede the forecast day, including crypto weekends.
    dates=series['dates'];j=np.searchsorted(dates,day,side='left')-1
    if j<0 or (datetime.fromisoformat(day)-datetime.fromisoformat(dates[j])).days>max_age:return None
    x=series['features'][dates[j]]
    return [x[1],x[4],x[8]],dates[j]

def records(hist,context,h,asset_class,inputs=None):
    inputs=inputs or {}
    rows=[];latest={};contexts={}
    for day in sorted({r['date'] for prices in hist.values() for r in prices}):
        extra=[];used=[]
        for key in (*PROXIES, *(('BTC',) if asset_class=='crypto' else ())):
            c=context_before(context[key],day)
            if c is None:break
            extra+=c[0];used.append(c[1])
        else:contexts[day]=(extra+([0.,0.,0.] if asset_class=='stocks' else []),max(used))
    ciks=inputs.get('symbolCIKs',{});representatives={}
    for symbol in sorted(hist):representatives.setdefault(ciks.get(symbol,symbol),symbol)
    for symbol,prices in hist.items():
        own=features(prices,365 if asset_class=='crypto' else 252)
        valid=[i for i in range(199,len(prices)) if prices[i]['date'] in contexts]
        if not valid:continue
        eligible=[i for i in valid if i==valid[-1] or (i+h<len(prices) and datetime.fromisoformat(prices[i]['date']).weekday()==(4 if asset_class=='stocks' else 6))]
        for i in eligible:
            day=prices[i]['date'];base=own[day];extra,used_through=contexts[day]
            current=dict(symbol=symbol,origin=day,anchor=prices[i]['close'],x=base,z=base+extra,contextThrough=used_through,regime=('상승' if extra[2]>=0 else '하락')+('·고변동' if extra[1]>=.3 else '·보통변동'))
            added,through=(stock_before(inputs.get('stocks',{}).get(symbol,{}).get('rows',[]),day) if asset_class=='stocks' else crypto_before(inputs.get('funding',{}).get(symbol,[]),inputs.get('snapshots',{}).get(symbol,[]),day))
            if asset_class=='stocks':
                quarterly,quarter_through=earnings_before(inputs.get('earnings',{}).get(symbol,[]),day)
                added+=quarterly
                through=max([d for d in (through,quarter_through) if d],default=None)
            current.update(w=current['z']+added,v=current['z']+[1. if math.isfinite(v) else float('nan') for v in added],inputThrough=through,inputCount=sum(math.isfinite(v) for v in added))
            latest[symbol]=current
            if symbol==representatives[ciks.get(symbol,symbol)] and i+h<len(prices) and datetime.fromisoformat(day).weekday()==(4 if asset_class=='stocks' else 6):
                if asset_class=='crypto' and (datetime.fromisoformat(prices[i+h]['date'])-datetime.fromisoformat(day)).days!=h:continue
                rows.append({**current,'targetDate':prices[i+h]['date'],'y':prices[i+h]['close']/prices[i]['close']})
    return rows,latest

def fit(train,field,balanced=False):
    # Same loss, parameters and label set: only context variables differ.
    y=np.array([r['y'] for r in train]);x=np.array([r[field] for r in train])
    return HistGradientBoostingRegressor(loss='absolute_error',max_iter=55,max_leaf_nodes=7,min_samples_leaf=25,l2_regularization=10,learning_rate=.05,early_stopping=False,random_state=23).fit(x,np.log(y) if balanced else y,sample_weight=None if balanced else 1/y)

def calibration(rows,origin):
    # Only earlier, out-of-sample, fully realized forecasts. No in-sample residuals.
    prior=[r for r in rows if r['targetDate']<origin and r.get('balanced',0)>0]
    dates=sorted({r['origin'] for r in prior})[-8:]
    prior=[r for r in prior if r['origin'] in dates]
    if len(dates)<3 or len(prior)<30:return None
    counts=Counter(r['origin'] for r in prior)
    values=sorted((abs(math.log(r['balanced']/r['y'])),1/counts[r['origin']]) for r in prior)
    target=.8*sum(w for _,w in values);total=0
    for q,w in values:
        total+=w
        if total>=target:break
    return dict(logRadius=q,n=len(prior),dates=len(dates),targetThrough=max(r['targetDate'] for r in prior),nominalCoverage=.8)

def interval_score(rows):
    rows=[r for r in rows if r.get('range')]
    if not rows:return dict(n=0,dates=0,coverage=None,logIntervalScore=None,widthRelativeToAnchor=None)
    values=[];covered=[];widths=[]
    for r in rows:
        lo,hi=r['range']['low'],r['range']['high'];y=r['y'];a,b,t=math.log(lo),math.log(hi),math.log(y)
        values.append(b-a+10*max(a-t,0)+10*max(t-b,0));covered.append(lo<=y<=hi);widths.append(hi-lo)
    return dict(n=len(rows),dates=len({r['origin'] for r in rows}),coverage=float(np.mean(covered)),logIntervalScore=float(np.mean(values)),widthRelativeToAnchor=float(np.mean(widths)))

def score(rows,name):
    rows=[r for r in rows if isinstance(r.get(name),(int,float)) and math.isfinite(r[name]) and r[name]>0]
    if not rows:return dict(n=0,dates=0,mape=None,p90=None,logMae=None,logBias=None,directionAccuracy=None)
    errors=np.array([abs(r[name]/r['y']-1) for r in rows]);dates=sorted({r['origin'] for r in rows})
    by={d:float(np.mean([errors[i] for i,r in enumerate(rows) if r['origin']==d])) for d in dates}
    sign=direction_label
    logs=np.array([math.log(r[name]/r['y']) for r in rows]);log_by={d:float(np.mean([abs(logs[i]) for i,r in enumerate(rows) if r['origin']==d])) for d in dates}
    down=[r for r in rows if sign(r['y'])==-1]
    return dict(n=len(rows),dates=len(dates),mape=float(errors.mean()),dateMeanMape=float(np.mean(list(by.values()))),p90=float(np.quantile(errors,.9)),logMae=float(np.mean(abs(logs))),logBias=float(logs.mean()),p90Log=float(np.quantile(abs(logs),.9)),dateMeanLogMae=float(np.mean(list(log_by.values()))),directionAccuracy=float(np.mean([sign(r[name])==sign(r['y']) for r in rows])),actualDownCount=len(down),downRecall=sum(sign(r[name])==-1 for r in down)/len(down) if down else None,over10Rate=float(np.mean(errors>.1)),byDate=by,logByDate=log_by)

def grouped_comparison(rows,sectors):
    groups=defaultdict(list)
    for row in rows:groups[sectors.get(row['symbol'],'Unknown')].append(row)
    return {sector:dict(issuers=len({r['symbol'] for r in group}),
        metrics={k:{a:b for a,b in score(group,k).items() if a not in ('byDate','logByDate')} for k in ('noChange','balanced','availabilityControl','enriched')},
        alwaysUpDirectionAccuracy=sum(r['y']>1.02 for r in group)/len(group)) for sector,group in sorted(groups.items())}

def compare(rows):
    # A later evaluation block is never used to choose the challenger.
    dates=sorted({r['origin'] for r in rows});boundary=len(dates)//2
    while boundary<len(dates)-2:
        earlier=[r for r in rows if r['origin']<dates[boundary] and r['targetDate']<dates[boundary]]
        if len({r['origin'] for r in earlier})>=3:break
        boundary+=1
    if boundary>=len(dates)-2:return dict(status='insufficient',passed=False,liveForecastChanged=False)
    start=dates[boundary];earlier=[r for r in rows if r['origin']<start and r['targetDate']<start];later=[r for r in rows if r['origin']>=start]
    if len({r['origin'] for r in earlier})<3:return dict(status='insufficient',passed=False,liveForecastChanged=False)
    candidates=[k for k in ('environment','ensemble','balanced','horizonModel') if all(r.get(k) for r in earlier)]
    choose=min(candidates,key=lambda k:score(earlier,k)['dateMeanLogMae']+.25*score(earlier,k)['p90Log'])
    names=NAMES+(('horizonModel',) if all(r.get('horizonModel') for r in later) else ())
    summary={k:score(later,k) for k in names};m=summary[choose]
    wins=sum(m['byDate'][d]<min(summary[k]['byDate'][d] for k in ('priceOnly','noChange')) for d in m['byDate'])/m['dates']
    checks=dict(enoughDates=m['dates']>=6,logError=m['dateMeanLogMae']<.95*min(summary[k]['dateMeanLogMae'] for k in ('priceOnly','noChange')),average=m['dateMeanMape']<=min(summary[k]['dateMeanMape'] for k in ('priceOnly','noChange')),tail=m['p90']<=min(summary[k]['p90'] for k in ('priceOnly','noChange')),consistency=wins>=.6,direction=m['directionAccuracy']>=max(summary[k]['directionAccuracy'] for k in ('priceOnly','noChange')),downRecall=m['actualDownCount']<30 or (m['downRecall'] is not None and m['downRecall']>=.10))
    return dict(status='research',chosen=choose,selectionTargetThrough=max(r['targetDate'] for r in earlier),evaluationStart=start,evaluationDates=dates[boundary:],selectionDates=sorted({r['origin'] for r in earlier}),evaluation=summary,checks=checks,passed=all(checks.values()),dateWinRate=wins,liveForecastChanged=False)

def run_class(hist,context,asset_class,inputs=None):
    output={};hs=(21,84,252) if asset_class=='stocks' else (30,120,365)
    for h in hs:
        data,latest=records(hist,context,h,asset_class,inputs);dates=sorted({r['origin'] for r in data});origins=[]
        # Index origins and matured labels once; never truncate the issuer universe.
        by_origin=defaultdict(list)
        for row in data:by_origin[row['origin']].append(row)
        matured=sorted(data,key=lambda r:r['targetDate']);target_dates=[r['targetDate'] for r in matured]
        seen=set();origin_counts=[0]
        for row in matured:seen.add(row['origin']);origin_counts.append(len(seen))
        end=''
        for origin in dates:
            if origin<=end:continue
            n=bisect_left(target_dates,origin)
            if n<300 or origin_counts[n]<40:continue
            origins.append(origin);end=max(r['targetDate'] for r in by_origin[origin])
        origins=origins[-18:];checks=[];folds=[]
        for origin in origins:
            train=[r for r in data if r['targetDate']<origin];test=by_origin[origin]
            print(asset_class,h,'fold',origin,'train',len(train),'test',len(test),flush=True)
            a=fit(train,'x');b=fit(train,'z');pa=a.predict(np.array([r['x'] for r in test]));pb=b.predict(np.array([r['z'] for r in test]))
            balanced=fit(train,'z',True);pc=np.exp(balanced.predict([r['z'] for r in test]));cal=calibration(checks,origin)
            usable=[r for r in train if r['inputCount']>0]
            enriched=fit(train,'w',True) if len(usable)>=300 and len({r['origin'] for r in usable})>=40 else None
            pe=np.exp(enriched.predict([r['w'] for r in test])) if enriched else [None]*len(test)
            control=fit(train,'v',True) if enriched else None
            pv=np.exp(control.predict([r['v'] for r in test])) if control else [None]*len(test)
            horizon_model=fit_horizon(train,h) if asset_class=='stocks' else None
            ph,probabilities=horizon_model.predict(test) if horizon_model else ([None]*len(test),[None]*len(test))
            folds.append(dict(origin=origin,trainTargetThrough=max(r['targetDate'] for r in train),targetThrough=max(r['targetDate'] for r in test),n=len(test),trainingRows=len(train),additionalInputTrainingRows=len(usable)))
            for r,v,w,z,e,mask,specific,probability in zip(test,pa,pb,pc,pe,pv,ph,probabilities):
                interval=dict(low=float(z*math.exp(-cal['logRadius'])),high=float(z*math.exp(cal['logRadius'])),**cal) if cal else None
                checks.append({k:r[k] for k in ('symbol','origin','targetDate','y','regime','contextThrough','inputThrough','inputCount')}|dict(noChange=1.,priceOnly=float(v),environment=float(w),ensemble=float((v+w)/2),balanced=float(z),horizonModel=float(specific) if specific is not None else None,horizonDirectionScores=probability,enriched=float(e) if e is not None and r['inputCount'] else None,availabilityControl=float(mask) if mask is not None and r['inputCount'] else None,range=interval))
        comparison=compare(checks);predictions={};models={};training_status={};calibrations={}
        for s,current in latest.items():
            origin=current['origin']
            if origin not in models:
                train=[r for r in data if r['targetDate']<origin]
                usable=[r for r in train if r['inputCount']>0]
                training_status[origin]=dict(totalRows=len(train),additionalInputRows=len(usable),additionalInputOrigins=len({r['origin'] for r in usable}),additionalInputIssuers=sorted({r['symbol'] for r in usable}),firstAdditionalInputOrigin=min((r['origin'] for r in usable),default=None),trainTargetThrough=max((r['targetDate'] for r in train),default=None))
                models[origin]=(fit(train,'x'),fit(train,'z'),fit(train,'z',True),fit(train,'w',True) if len(usable)>=300 and len({r['origin'] for r in usable})>=40 else None,fit_horizon(train,h) if asset_class=='stocks' else None,max(r['targetDate'] for r in train)) if len(train)>=300 else None
            if not models[origin]:continue
            a,b,c,e,specific_model,through=models[origin];v=float(a.predict([current['x']])[0]);w=float(b.predict([current['z']])[0]);z=float(np.exp(c.predict([current['z']])[0]));own=[r for r in checks if r['symbol']==s]
            specific,specific_probability=specific_model.predict([current]) if specific_model else ([None],[None])
            if origin not in calibrations:calibrations[origin]=calibration(checks,origin)
            cal=calibrations[origin]
            names=NAMES+(('horizonModel',) if asset_class=='stocks' else ())
            predictions[s]=dict(asOf=origin,anchor=current['anchor'],contextThrough=current['contextThrough'],trainTargetThrough=through,regime=current['regime'],priceOnly=current['anchor']*v,environment=current['anchor']*w,ensemble=current['anchor']*(v+w)/2,balanced=current['anchor']*z,horizonModel=current['anchor']*float(specific[0]) if specific[0] is not None else None,horizonDirectionScores=specific_probability[0],enriched=current['anchor']*float(np.exp(e.predict([current['w']])[0])) if e and current['inputCount'] else None,inputThrough=current['inputThrough'],inputValues={k:float(val) if math.isfinite(val) else None for k,val in zip(STOCK_FIELDS+EARNINGS_FIELDS if asset_class=='stocks' else CRYPTO_FIELDS,current['w'][-(len(STOCK_FIELDS)+len(EARNINGS_FIELDS) if asset_class=='stocks' else len(CRYPTO_FIELDS)):])},range=dict(low=current['anchor']*z*math.exp(-cal['logRadius']),high=current['anchor']*z*math.exp(cal['logRadius']),**cal) if cal else None,rangeValidation=interval_score(own),validation={k:{a:b for a,b in score(own,k).items() if a not in ('byDate','logByDate')} for k in names})
        later=[r for r in checks if r['origin']>=comparison.get('evaluationStart','9999')]
        paired=[r for r in later if r.get('enriched') is not None]
        names=NAMES+(('horizonModel',) if asset_class=='stocks' else ())
        horizon_evaluation=score(later,'horizonModel') if asset_class=='stocks' else None
        profile={k:v for k,v in HORIZON_PROFILES[h].items() if k not in ('direction_probability','direction_margin')} if asset_class=='stocks' else None
        horizon_specific=dict(profile=profile,evaluation=horizon_evaluation,directionCounts={label:sum(1 for r in later if (r.get('horizonModel',1)>1.02 if label=='up' else r.get('horizonModel',1)<.98 if label=='down' else .98<=r.get('horizonModel',1)<=1.02)) for label in ('up','flat','down')},liveForecastChanged=False) if asset_class=='stocks' else None
        output[str(h)]=dict(comparison=comparison,trainingStatus=training_status,allDates={k:score(checks,k) for k in names},rangeValidation=interval_score(later),horizonSpecific=horizon_specific,enrichment=dict(evaluation={k:score(paired,k) for k in ('balanced','availabilityControl','enriched')},alwaysUpDirectionAccuracy=float(np.mean([r['y']>1.02 for r in paired])) if paired else None,directionCounts={k:{label:sum(1 for r in paired if (r[k]>1.02 if label=='up' else r[k]<.98 if label=='down' else .98<=r[k]<=1.02)) for label in ('up','flat','down')} for k in ('balanced','enriched')},matchedBySymbol={s:sum(r['symbol']==s for r in paired) for s in sorted({r['symbol'] for r in paired})},matchedRows=len(paired),totalLaterRows=len(later),liveForecastChanged=False),regimes={g:{k:score([r for r in checks if r['regime']==g],k) for k in names} for g in sorted({r['regime'] for r in checks})},folds=folds,predictions=predictions,outcomes=checks)
        print(asset_class,h,'disjoint dates',len(folds),'later pass',comparison.get('passed'),flush=True)
        if asset_class=='stocks':
            output[str(h)]['enrichment']['evaluation']['noChange']=score(paired,'noChange')
            output[str(h)]['enrichment']['bySector']=grouped_comparison(paired,(inputs or {}).get('sectors',{}))
    return output

def build(root=ROOT,download=True,stocks_only=False):
    now=datetime.now(timezone.utc);today=now.date().isoformat();folder=root/'research/history';folder.mkdir(parents=True,exist_ok=True);hist={};errors=[];halt=not download
    manifest=load_universe(root);members=manifest['members'];stock_symbols=tuple(members)
    for sym in dict.fromkeys((*PROXIES,*stock_symbols)):
        path=folder/(sym.replace('^','INDEX_')+'.json')
        try:
            if halt:
                if not path.exists():raise ValueError('No cached history')
                hist[sym]=json.loads(path.read_text())['prices']
            else:hist[sym]=fetch_history(sym,folder,today);print('History',sym,len(hist[sym]),flush=True);time.sleep(.25)
        except Exception as e:
            if isinstance(e,HTTPError) and e.code in (401,403,429):halt=True
            errors.append(sym+': '+str(e))
            if path.exists():hist[sym]=json.loads(path.read_text())['prices']
    if any(k not in hist for k in PROXIES):raise ValueError('Context inputs missing: '+str(errors))
    from build_crypto_learned import histories,YAHOO,aligned,clean
    crypto,_=histories(root,json.loads((root/'crypto/latest.json').read_text()),now,download=False)
    crypto={s:v['rows'] for s,v in crypto.items() if v['rows']}
    for sym,(ticker,_) in ({} if stocks_only else YAHOO).items():
        if sym not in crypto:continue
        path=folder/(ticker+'.json')
        try:
            candidate=fetch_history(ticker,folder,today) if download and not halt else json.loads(path.read_text())['prices'] if path.exists() else []
            candidate=clean(candidate)
            if len(candidate)>len(crypto[sym]) and aligned(candidate,crypto[sym]):crypto[sym]=candidate
        except Exception as e:
            if isinstance(e,HTTPError) and e.code in (401,403,429):halt=True
            errors.append(ticker+': '+str(e))
    context={} 
    for sym,prices in {**{k:hist[k] for k in PROXIES},'BTC':crypto['BTC']}.items():
        f=features(prices,365 if sym=='BTC' else 252);context[sym]=dict(features=f,dates=np.array(sorted(f)))
    universe={s:hist[s] for s in stock_symbols if s in hist and len(hist[s])>=200}
    ip=root/'research/inputs.json';inputs=json.loads(ip.read_text()) if ip.exists() else {}
    ep=root/'research/earnings.json';earnings=json.loads(ep.read_text()) if ep.exists() else {}
    inputs['earnings']=earnings.get('issuers',{})
    inputs['symbolCIKs']={s:v['cik'] for s,v in members.items()}
    inputs['sectors']={s:v['sector'] for s,v in members.items()}
    out=dict(model=MODEL,generatedAt=now.isoformat(),stocks=run_class(universe,context,'stocks',inputs),crypto=(json.loads((root/'research/environment.json').read_text())['crypto'] if stocks_only else run_class(crypto,context,'crypto',inputs)),errors=errors,stockUniverse=list(universe),history={s:dict(firstDate=r[0]['date'],lastDate=r[-1]['date'],count=len(r)) for s,r in {**universe,**crypto}.items()},contextLabels=PROXIES,historyHashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.json')},cryptoInputHashes={s:hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest() for s,r in crypto.items()},additionalInputHash=hashlib.sha256(ip.read_bytes()).hexdigest() if ip.exists() else None,inputStatus=dict(generatedAt=inputs.get('generatedAt'),errors=inputs.get('errors',[]),stocks={s:dict(rows=len(v['rows']),firstDate=v['rows'][0]['availableDate'] if v['rows'] else None,lastDate=v['rows'][-1]['availableDate'] if v['rows'] else None) for s,v in inputs.get('stocks',{}).items()},funding={s:dict(days=len(v),firstDate=v[0]['date'] if v else None,lastDate=v[-1]['date'] if v else None) for s,v in inputs.get('funding',{}).items()},snapshots={s:dict(days=len(v),firstDate=v[0]['date'] if v else None,lastDate=v[-1]['date'] if v else None) for s,v in inputs.get('snapshots',{}).items()}),limitations=['Current S&P 500 constituent snapshot, not historical membership; survivorship bias remains. One representative ticker per CIK enters training and evaluation; all available share classes receive predictions.','Adjusted historical prices may be revised; SEC filed-date reconstruction is not a certified vintage feed.','NVDA/MSFT original quarterly GAAP earnings and explicit NVIDIA revenue guidance only; no analyst surprises or narrative history.','HYG and IEF prices are market proxies, not credit spreads or policy rates.','Context and publication dates strictly precede origin; no future macro inputs.','Same-date assets are correlated; annual outcomes are disjoint, not statistically independent.','Revisited historical holdout; not new prospective evidence.','80% is a calibration target, not guaranteed future coverage; pooled residuals may miss asset/regime changes.','No automatic promotion; historical improvement does not ensure future improvement.','Foundation models such as Chronos/TimesFM have not been run in this experiment.'])
    out['universeCoverage']=dict(source=manifest['source'],retrievedAt=manifest['retrievedAt'],sourceHash=manifest['sourceHash'],targetTickers=len(members),targetIssuers=manifest['issuerCount'],priceTickers=len(universe),priceIssuers=len({members[s]['cik'] for s in universe}),missingPrices={s:('insufficient_price_history' if s in hist else 'price_unavailable') for s in members if s not in universe},sec=inputs.get('secCoverage',{}))
    out['sectors']={s:v['sector'] for s,v in members.items()}
    out['earningsInputHash']=hashlib.sha256(ep.read_bytes()).hexdigest() if ep.exists() else None
    out['inputStatus']['earnings']=dict(generatedAt=earnings.get('generatedAt'),coverage=earnings.get('coverage',{}),errors=earnings.get('errors',[]))
    if stocks_only:
        previous=json.loads((root/'research/environment.json').read_text())
        out['cryptoGeneratedAt']=previous.get('cryptoGeneratedAt',previous['generatedAt'])
        out['cryptoModel']=previous.get('cryptoModel',previous['model'])
        out['cryptoInputHashes']=previous.get('cryptoInputHashes',{})
        for symbol in crypto:
            if symbol in previous.get('history',{}):out['history'][symbol]=previous['history'][symbol]
    atomic_json(root/'research/environment.json',out)
    archive_path=root/'research/issued.json';archive=json.loads(archive_path.read_text()) if archive_path.exists() else []
    keys={(r['model'],r['assetClass'],r['symbol'],r['asOf'],r['horizon']) for r in archive}
    for cls in (('stocks',) if stocks_only else ('stocks','crypto')):
        for h,v in out[cls].items():
            for symbol,p in v['predictions'].items():
                key=(MODEL,cls,symbol,p['asOf'],h)
                if key not in keys:
                    archive.append(dict(model=MODEL,assetClass=cls,symbol=symbol,asOf=p['asOf'],horizon=h,issuedAt=now.isoformat(),anchor=p['anchor'],balanced=p['balanced'],horizonModel=p.get('horizonModel'),horizonDirectionScores=p.get('horizonDirectionScores'),enriched=p['enriched'],range=p['range']));keys.add(key)
    atomic_json(archive_path,archive);return out
if __name__=='__main__':
    import sys
    build(download='--offline' not in sys.argv,stocks_only='--stocks-only' in sys.argv)
