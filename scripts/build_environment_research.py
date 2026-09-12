"""Fixed public-data challenger experiment; no trade records, no automatic promotion."""
import os
os.environ.setdefault('OMP_NUM_THREADS','2')
import json, math, hashlib
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from build_forecasts import atomic_json
ROOT=Path(__file__).resolve().parents[1]
STOCKS=('NVDA','AMD','AVGO','MU','AMAT','QCOM','INTC','MSFT','AAPL','GOOGL','AMZN','META','TSLA','JPM','XOM','SPY')
PROXIES={'SPY':'미국 주식','QQQ':'기술주','HYG':'하이일드 채권 가격','IEF':'중기 국채 가격','UUP':'달러 ETF','^VIX':'VIX'}
BASE=['return7','return30','return90','return180','vol30','vol90','distance20','distance50','distance200','drawdown90']
CONTEXT=[f'{s}_{k}' for s in PROXIES for k in ('return30','vol30','distance200')]+['BTC_return30','BTC_vol30','BTC_distance200']
NAMES=('noChange','priceOnly','environment','ensemble')
MODEL='environment-challenger-v1'
def fetch_history(symbol,folder,today):
    path=folder/(symbol.replace('^','INDEX_')+'.json')
    old=json.loads(path.read_text()) if path.exists() else {}
    if old.get('checkedDate')==today:return old['prices']
    u='https://query1.finance.yahoo.com/v8/finance/chart/'+symbol+'?range=20y&interval=1d'
    with urlopen(Request(u,headers={'User-Agent':'DashboardEnvironmentResearch/1.0'}),timeout=25) as r:d=json.load(r)
    q=d['chart']['result'][0]
    if q['meta']['symbol']!=symbol:raise ValueError('Asset identity mismatch')
    close=q['indicators'].get('adjclose',[{}])[0].get('adjclose',q['indicators']['quote'][0]['close'])
    rows=[]
    for t,p in zip(q['timestamp'],close):
        day=datetime.fromtimestamp(t,timezone.utc).date().isoformat()
        if day<today and p is not None and math.isfinite(p) and p>0:rows.append({'date':day,'close':float(p)})
    atomic_json(path,{'symbol':symbol,'source':'Yahoo adjusted daily close','checkedDate':today,'prices':rows})
    return rows

def features(rows,annual_days=252):
    out={};p=np.array([r['close'] for r in rows]);ret=np.diff(np.log(p))
    for i in range(199,len(rows)):
        a=p[i-199:i+1];r=ret[i-90:i]
        x=[float(np.log(p[i]/p[i-n])) for n in (7,30,90,180)]
        x += [float(np.std(r[-n:],ddof=1)*np.sqrt(annual_days)) for n in (30,90)]
        x += [float(p[i]/a[-n:].mean()-1) for n in (20,50,200)]
        x += [float(p[i]/a[-90:].max()-1)]
        out[rows[i]['date']]=x
    return out

def context_before(series,day,max_age=5):
    # Every context close must precede the forecast day, including crypto weekends.
    dates=series['dates'];j=np.searchsorted(dates,day,side='left')-1
    if j<0 or (datetime.fromisoformat(day)-datetime.fromisoformat(dates[j])).days>max_age:return None
    x=series['features'][dates[j]]
    return [x[1],x[4],x[8]],dates[j]

def records(hist,context,h,asset_class):
    rows=[];latest={}
    for symbol,prices in hist.items():
        own=features(prices,365 if asset_class=='crypto' else 252)
        for i in range(199,len(prices)):
            day=prices[i]['date'];base=own[day];extra=[];used=[]
            for key in PROXIES:
                c=context_before(context[key],day)
                if c is None:break
                extra+=c[0];used.append(c[1])
            else:
                if asset_class=='crypto':
                    c=context_before(context['BTC'],day)
                    if c is None:continue
                    extra+=c[0];used.append(c[1])
                else:extra += [0.,0.,0.]
                current=dict(symbol=symbol,origin=day,anchor=prices[i]['close'],x=base,z=base+extra,contextThrough=max(used),regime=('상승' if extra[2]>=0 else '하락')+('·고변동' if extra[1]>=.3 else '·보통변동'))
                latest[symbol]=current
                if i+h<len(prices) and datetime.fromisoformat(day).weekday()==(4 if asset_class=='stocks' else 6):
                    if asset_class=='crypto' and (datetime.fromisoformat(prices[i+h]['date'])-datetime.fromisoformat(day)).days!=h:continue
                    rows.append({**current,'targetDate':prices[i+h]['date'],'y':prices[i+h]['close']/prices[i]['close']})
    return rows,latest

def fit(train,field):
    # Same loss, parameters and label set: only context variables differ.
    y=np.array([r['y'] for r in train]);x=np.array([r[field] for r in train])
    return HistGradientBoostingRegressor(loss='absolute_error',max_iter=55,max_leaf_nodes=7,min_samples_leaf=25,l2_regularization=10,learning_rate=.05,early_stopping=False,random_state=23).fit(x,y,sample_weight=1/y)

def score(rows,name):
    if not rows:return dict(n=0,dates=0,mape=None,p90=None,directionAccuracy=None)
    errors=np.array([abs(r[name]/r['y']-1) for r in rows]);dates=sorted({r['origin'] for r in rows})
    by={d:float(np.mean([errors[i] for i,r in enumerate(rows) if r['origin']==d])) for d in dates}
    sign=lambda x:1 if x>1.02 else -1 if x<.98 else 0
    return dict(n=len(rows),dates=len(dates),mape=float(errors.mean()),dateMeanMape=float(np.mean(list(by.values()))),p90=float(np.quantile(errors,.9)),directionAccuracy=float(np.mean([sign(r[name])==sign(r['y']) for r in rows])),over10Rate=float(np.mean(errors>.1)),byDate=by)

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
    choose=min(('environment','ensemble'),key=lambda k:score(earlier,k)['dateMeanMape']+.25*score(earlier,k)['p90'])
    summary={k:score(later,k) for k in NAMES};m=summary[choose]
    wins=sum(m['byDate'][d]<min(summary[k]['byDate'][d] for k in ('priceOnly','noChange')) for d in m['byDate'])/m['dates']
    checks=dict(enoughDates=m['dates']>=6,average=m['dateMeanMape']<.95*min(summary[k]['dateMeanMape'] for k in ('priceOnly','noChange')),tail=m['p90']<=min(summary[k]['p90'] for k in ('priceOnly','noChange')),consistency=wins>=.6,direction=m['directionAccuracy']>=max(summary[k]['directionAccuracy'] for k in ('priceOnly','noChange')))
    return dict(status='research',chosen=choose,selectionTargetThrough=max(r['targetDate'] for r in earlier),evaluationStart=start,evaluationDates=dates[boundary:],selectionDates=sorted({r['origin'] for r in earlier}),evaluation=summary,checks=checks,passed=all(checks.values()),dateWinRate=wins,liveForecastChanged=False)

def run_class(hist,context,asset_class):
    output={};hs=(21,84,252) if asset_class=='stocks' else (30,120,365)
    for h in hs:
        data,latest=records(hist,context,h,asset_class);dates=sorted({r['origin'] for r in data});origins=[]
        # Disjoint outcome windows, not merely different origin dates.
        end=''
        for origin in dates:
            test=[r for r in data if r['origin']==origin]
            if origin<=end:continue
            train=[r for r in data if r['targetDate']<origin]
            if len(train)<300 or len({r['origin'] for r in train})<40:continue
            origins.append(origin);end=max(r['targetDate'] for r in test)
        origins=origins[-18:];checks=[];folds=[]
        for origin in origins:
            train=[r for r in data if r['targetDate']<origin];test=[r for r in data if r['origin']==origin]
            a=fit(train,'x');b=fit(train,'z');pa=a.predict(np.array([r['x'] for r in test]));pb=b.predict(np.array([r['z'] for r in test]))
            folds.append(dict(origin=origin,trainTargetThrough=max(r['targetDate'] for r in train),targetThrough=max(r['targetDate'] for r in test),n=len(test)))
            for r,v,w in zip(test,pa,pb):checks.append({k:r[k] for k in ('symbol','origin','targetDate','y','regime','contextThrough')}|dict(noChange=1.,priceOnly=float(v),environment=float(w),ensemble=float((v+w)/2)))
        comparison=compare(checks);predictions={};models={}
        for s,current in latest.items():
            origin=current['origin']
            if origin not in models:
                train=[r for r in data if r['targetDate']<origin]
                models[origin]=(fit(train,'x'),fit(train,'z'),max(r['targetDate'] for r in train)) if len(train)>=300 else None
            if not models[origin]:continue
            a,b,through=models[origin];v=float(a.predict([current['x']])[0]);w=float(b.predict([current['z']])[0]);own=[r for r in checks if r['symbol']==s]
            predictions[s]=dict(asOf=origin,anchor=current['anchor'],contextThrough=current['contextThrough'],trainTargetThrough=through,regime=current['regime'],priceOnly=current['anchor']*v,environment=current['anchor']*w,ensemble=current['anchor']*(v+w)/2,validation={k:score(own,k) for k in NAMES})
        output[str(h)]=dict(comparison=comparison,allDates={k:score(checks,k) for k in NAMES},regimes={g:{k:score([r for r in checks if r['regime']==g],k) for k in NAMES} for g in sorted({r['regime'] for r in checks})},folds=folds,predictions=predictions,outcomes=checks)
        print(asset_class,h,'disjoint dates',len(folds),'later pass',comparison.get('passed'),flush=True)
    return output

def build(root=ROOT,download=True):
    now=datetime.now(timezone.utc);today=now.date().isoformat();folder=root/'research/history';folder.mkdir(parents=True,exist_ok=True);hist={};errors=[];halt=not download
    for sym in dict.fromkeys((*STOCKS,*PROXIES)):
        path=folder/(sym.replace('^','INDEX_')+'.json')
        try:
            if halt:
                if not path.exists():raise ValueError('No cached history')
                hist[sym]=json.loads(path.read_text())['prices']
            else:hist[sym]=fetch_history(sym,folder,today);print('History',sym,len(hist[sym]),flush=True)
        except Exception as e:
            if isinstance(e,HTTPError) and e.code in (401,403,429):halt=True
            errors.append(sym+': '+str(e))
            if path.exists():hist[sym]=json.loads(path.read_text())['prices']
    if any(k not in hist for k in PROXIES):raise ValueError('Context inputs missing: '+str(errors))
    from build_crypto_learned import histories,YAHOO,aligned,clean
    crypto,_=histories(root,json.loads((root/'crypto/latest.json').read_text()),now,download=False)
    crypto={s:v['rows'] for s,v in crypto.items() if v['rows']}
    for sym,(ticker,_) in YAHOO.items():
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
    universe={s:hist[s] for s in STOCKS if s in hist}
    out=dict(model=MODEL,generatedAt=now.isoformat(),stocks=run_class(universe,context,'stocks'),crypto=run_class(crypto,context,'crypto'),errors=errors,stockUniverse=list(universe),history={s:dict(firstDate=r[0]['date'],lastDate=r[-1]['date'],count=len(r)) for s,r in {**universe,**crypto}.items()},contextLabels=PROXIES,historyHashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.json')},cryptoInputHashes={s:hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest() for s,r in crypto.items()},limitations=['Representative current-universe pilot, not all stocks; survivorship bias remains.','Adjusted historical prices may be revised; no point-in-time fundamentals/news/supply inputs.','HYG and IEF prices are market proxies, not credit spreads or policy rates.','Context closes strictly precede origin; no future macro inputs.','Same-date assets are correlated; annual outcomes are disjoint, not statistically independent.','Later evaluation is held out from candidate selection, not prospective trading evidence.','No automatic promotion; historical improvement does not ensure future improvement.','Foundation models such as Chronos/TimesFM have not been run in this experiment.'])
    atomic_json(root/'research/environment.json',out);return out
if __name__=='__main__':
    import sys
    build(download='--offline' not in sys.argv)
