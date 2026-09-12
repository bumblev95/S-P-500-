"""Read-only public OHLC and funding inputs for the paper-account experiment."""
import json,math,threading
from pathlib import Path
from datetime import datetime,timezone
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor
from build_forecasts import atomic_json

ROOT=Path(__file__).resolve().parents[1]
HL='https://api.hyperliquid.xyz/info'
STOCKS={'NVDA':'기술','MSFT':'기술','AAPL':'기술','AMD':'기술','GOOGL':'통신','META':'통신',
        'AMZN':'경기소비','JPM':'금융','BAC':'금융','XOM':'에너지','CVX':'에너지','JNJ':'헬스케어',
        'LLY':'헬스케어','UNH':'헬스케어','WMT':'필수소비','COST':'필수소비','PG':'필수소비',
        'CAT':'산업재','GE':'산업재','NEE':'유틸리티','SPY':'시장 기준'}
COINS=('BTC','ETH','SOL')
HALTED=set();LOCK=threading.Lock()

def fetch(url,body=None):
    host='HL' if url==HL else 'Yahoo'
    with LOCK:
        if host in HALTED:raise RuntimeError(host+' access/rate limit; stopped')
    try:
        req=Request(url,data=json.dumps(body).encode() if body else None,
                    headers={'User-Agent':'PublicPaperTradingResearch/1.0','Content-Type':'application/json'})
        with urlopen(req,timeout=20) as r:return json.load(r)
    except HTTPError as e:
        if e.code in (401,403,429):
            with LOCK:HALTED.add(host)
        raise

def valid(r):
    return all(isinstance(r.get(k),(float,int)) and math.isfinite(r[k]) for k in ('t','end','open','high','low','close','volume')) and r['t']<r['end'] and 0<r['low']<=min(r['open'],r['close'])<=max(r['open'],r['close'])<=r['high'] and r['volume']>=0

def merge(old,new):
    # Freeze first observed completed candles. Flag material revisions; never
    # silently rewrite old fills or split-adjust an open paper position.
    out={r['t']:r for r in old};revisions=[]
    for r in new:
        if not valid(r):continue
        previous=out.get(r['t'])
        if previous and any(abs(r[k]/previous[k]-1)>.005 for k in ('open','high','low','close')):
            revisions.append(r['t'])
        if previous is None:out[r['t']]=r
    return sorted(out.values(),key=lambda r:r['t']),revisions

def collect(root=ROOT,now=None):
    now=now or datetime.now(timezone.utc);ms=int(now.timestamp()*1000);path=root/'simulation/market.json'
    old=json.loads(path.read_text()) if path.exists() else {};data=dict(schemaVersion=1,generatedAt=now.isoformat(),stocks={},crypto={},errors=[])
    def stock(symbol):
        prior=old.get('stocks',{}).get(symbol,{})
        if prior.get('checkedDate')==now.date().isoformat():return symbol,prior,None
        try:
            raw=fetch('https://query1.finance.yahoo.com/v8/finance/chart/'+symbol+'?range=3y&interval=1d')['chart']['result'][0]
            if raw['meta']['symbol']!=symbol:raise ValueError('Symbol mismatch')
            q=raw['indicators']['quote'][0];rows=[]
            for i,t in enumerate(raw.get('timestamp',[])):
                d=datetime.fromtimestamp(t,timezone.utc).date().isoformat()
                if d>=now.date().isoformat():continue
                try:r=dict(t=t*1000,end=t*1000+23400000-1,date=d,**{k:float(q[k][i]) for k in ('open','high','low','close','volume')})
                except (TypeError,IndexError):continue
                if valid(r):rows.append(r)
            rows,revisions=merge(prior.get('rows',[]),rows)
            if len(rows)<220:raise ValueError('Fewer than 220 complete sessions')
            return symbol,dict(rows=rows,sector=STOCKS[symbol],checkedDate=now.date().isoformat(),fetchedAt=now.isoformat(),revisions=sorted(set(prior.get('revisions',[])+revisions)),source='Yahoo daily OHLC; dividends excluded'),None
        except Exception as e:return symbol,dict(prior,errors=[str(e)]) if prior else prior,symbol+': '+str(e)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for s,value,error in pool.map(stock,STOCKS):
            if value:data['stocks'][s]=value
            if error:data['errors'].append(error)
    for symbol in COINS:
        prior=old.get('crypto',{}).get(symbol,{});item=dict(prior);item['source']='Hyperliquid perpetual OHLC';item['frames']=dict(prior.get('frames',{}));errors=[]
        for interval,step,count in [('15m',900000,4800),('1h',3600000,1300)]:
            try:
                previous=item['frames'].get(interval,[]);start=previous[-2]['t'] if len(previous)>2 else ms-step*count
                raw=fetch(HL,dict(type='candleSnapshot',req=dict(coin=symbol,interval=interval,startTime=start,endTime=ms)))
                rows=[]
                for q in raw:
                    if q.get('s')!=symbol or q.get('i')!=interval or q['T']>=ms:continue
                    r={k:float(q[v]) for k,v in [('open','o'),('high','h'),('low','l'),('close','c'),('volume','v')]}
                    r.update(t=q['t'],end=q['T'])
                    if valid(r) and r['t']%step==0 and r['end']==r['t']+step-1:rows.append(r)
                item['frames'][interval],revisions=merge(previous,rows)
                item['revisions']=sorted(set(item.get('revisions',[])+revisions))
            except Exception as e:errors.append(symbol+' '+interval+': '+str(e))
        try:
            funding={q['time']:q for q in prior.get('funding',[])}
            start=max(funding)+1 if funding else (item['frames'].get('15m') or [{'t':ms}])[0]['t']
            for page in range(8):
                raw=fetch(HL,dict(type='fundingHistory',coin=symbol,startTime=start,endTime=ms))
                if not isinstance(raw,list):raise ValueError('Invalid funding response')
                for q in raw:
                    rate=float(q['fundingRate'])
                    if q.get('coin')==symbol and math.isfinite(rate) and q['time']<ms:funding.setdefault(q['time'],dict(time=q['time'],rate=rate))
                if not raw or len(raw)<500:break
                next_start=max(q['time'] for q in raw)+1
                if next_start<=start:raise ValueError('Funding pagination stalled')
                start=next_start
            item['funding']=sorted(funding.values(),key=lambda q:q['time'])
        except Exception as e:errors.append(symbol+' funding: '+str(e))
        item['fetchedAt']=now.isoformat();item['errors']=errors;data['crypto'][symbol]=item;data['errors']+=errors
        print('Simulation data',symbol,{k:len(v) for k,v in item['frames'].items()},len(item.get('funding',[])),flush=True)
    atomic_json(path,data);print('Simulation stocks',len(data['stocks']),'errors',len(data['errors']),flush=True)
    return data

if __name__=='__main__':collect()
