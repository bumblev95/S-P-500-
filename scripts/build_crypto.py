"""Public crypto rules: separate spot/supply and perpetual data; no trading or AI claims."""
import json,math,statistics,threading,time
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor
from build_forecasts import atomic_json
ROOT=Path(__file__).resolve().parents[1]
COINS={'BTC':'bitcoin','ETH':'ethereum','SOL':'solana','BNB':'binancecoin','XRP':'ripple','DOGE':'dogecoin','LINK':'chainlink','AVAX':'avalanche-2','SUI':'sui','ARB':'arbitrum','HYPE':'hyperliquid','SKR':'seeker'}
HL='https://api.hyperliquid.xyz/info'
HALTED=set();LOCK=threading.Lock();CG_LOCK=threading.Lock();CG_NEXT=0
def number(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):return None
def clamp(x,a=0,b=100):return max(a,min(b,x))
def age_hours(s,now):
    try:return (now-datetime.fromisoformat(s.replace('Z','+00:00'))).total_seconds()/3600
    except (ValueError,TypeError,AttributeError):return float('inf')
def fresh(s,now,h=2):return 0<=age_hours(s,now)<=h
def request(url,body=None):
    global CG_NEXT
    host='HL' if url==HL else 'CG'
    if host=='CG':
        with CG_LOCK:
            with LOCK:
                if host in HALTED:raise RuntimeError(host+' rate/access limit; no retry')
            time.sleep(max(0,CG_NEXT-time.monotonic()))
            CG_NEXT=time.monotonic()+12
    with LOCK:
        if host in HALTED:raise RuntimeError(host+' rate/access limit; no retry')
    try:
        req=Request(url,data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json','User-Agent':'CryptoResearchDashboard/1.0'})
        with urlopen(req,timeout=20) as r:return json.load(r)
    except HTTPError as e:
        if e.code in (401,403,429):
            with LOCK:HALTED.add(host)
        raise
def candles(raw,now_ms):
    rows={}
    for r in raw:
        v={k:number(r.get(src)) for k,src in [('open','o'),('high','h'),('low','l'),('close','c'),('volume','v')]}
        if number(r.get('T')) is None or r['T']>=now_ms or any(v[k] is None or v[k]<=0 for k in ['open','high','low','close']):continue
        if not v['low']<=min(v['open'],v['close'])<=max(v['open'],v['close'])<=v['high']:continue
        d=datetime.fromtimestamp(r['t']/1000,timezone.utc).date().isoformat();rows[d]=dict(date=d,**v)
    return [rows[d] for d in sorted(rows)]
def ema(p,n):
    out=[];v=p[0]
    for x in p:v+=(x-v)*2/(n+1);out.append(v)
    return out
def indicators(rows):
    if len(rows)<60:return None
    p=[r['close'] for r in rows];returns=[math.log(b/a) for a,b in zip(p,p[1:])]
    gains=[max(b-a,0) for a,b in zip(p,p[1:])];losses=[max(a-b,0) for a,b in zip(p,p[1:])]
    g=statistics.mean(gains[:14]);l=statistics.mean(losses[:14])
    for a,b in zip(gains[14:],losses[14:]):g=(13*g+a)/14;l=(13*l+b)/14
    rsi=50 if g+l==0 else 100 if l==0 else 100-100/(1+g/l)
    m=[a-b for a,b in zip(ema(p,12),ema(p,26))];hist=m[-1]-ema(m,9)[-1]
    tr=[max(r['high']-r['low'],abs(r['high']-p[i-1]),abs(r['low']-p[i-1])) for i,r in enumerate(rows) if i>0]
    atr=statistics.mean(tr[:14])
    for x in tr[14:]:atr=(13*atr+x)/14
    ma20=statistics.mean(p[-20:]);ma50=statistics.mean(p[-50:]);ma200=statistics.mean(p[-200:]) if len(p)>=200 else None
    score=50+(12 if p[-1]>=ma20 else -12)+(12 if ma20>=ma50 else -12)+(10 if hist>=0 else -10)+(8 if 45<=rsi<=65 else -8 if rsi>75 or rsi<30 else 0)
    if ma200 is not None:score+=8 if p[-1]>=ma200 else -8
    drift=clamp(.25*(.6*math.log(p[-1]/p[-8])/7+.4*math.log(p[-1]/p[-31])/30),-.002,.002)
    return dict(trend=clamp(score),rsi=rsi,macdHistogram=hist,atr=atr,ma20=ma20,ma50=ma50,ma200=ma200,volatility=statistics.stdev(returns[-60:])*math.sqrt(365),drift=drift,return7=p[-1]/p[-8]-1,return30=p[-1]/p[-31]-1)
def forecast(price,ind,h):
    c=ind['drift']*60*(1-math.exp(-h/60));w=ind['volatility']*math.sqrt(h/365)
    return dict(horizon=h,base=price*math.exp(c),bear=price*math.exp(c-w),bull=price*math.exp(c+w))
def backtest(rows,h):
    errors=[];baseline=[];origins=[]
    for i in range(len(rows)-h-1,199,-h):
        f=forecast(rows[i]['close'],indicators(rows[:i+1]),h);actual=rows[i+h]['close']
        errors.append(abs(f['base']/actual-1));baseline.append(abs(rows[i]['close']/actual-1));origins.append(rows[i]['date'])
        if len(errors)>=12:break
    return dict(n=len(errors),mape=statistics.mean(errors) if errors else None,baselineMape=statistics.mean(baseline) if errors else None,origins=origins)
def spot_points(raw,now):
    """Keep UTC midnight spot observations; exclude the appended live-price point."""
    rows={}
    for t,price in raw.get('prices',[]):
        price=number(price)
        if not price or price<=0 or not isinstance(t,(int,float)) or t%86400000!=0 or t>now.timestamp()*1000:continue
        at=datetime.fromtimestamp(t/1000,timezone.utc)
        date=(at-timedelta(milliseconds=1)).date().isoformat()
        rows[date]=dict(date=date,at=at.isoformat(),close=price)
    return [rows[d] for d in sorted(rows)]
def spot_rows(e):
    # Close-only adapter: ATR is not used for spot levels and is never presented as OHLC ATR.
    return [dict(r,open=r['close'],high=r['close'],low=r['close'],volume=None) for r in e.get('spotHistory',[])]
def spot_assess(e,btc,now):
    rows=spot_rows(e);view=dict(e,history=rows,perp={},book={});a=assess(view,btc,now)
    a={k:a[k] for k in ['indicators','score','coverage','components','floatRatio','fdvRatio','spotBlocks']}
    a['levels']={};a['spotAction']='관망';ind=a['indicators'];price=(e.get('spot') or {}).get('price')
    if not ind or not price:return a
    p=[r['close'] for r in rows];moves=[abs(y-x) for x,y in zip(p,p[1:])];buffer=statistics.mean(moves[-14:])
    below=[];above=[]
    for i in range(max(2,len(p)-160),len(p)-2):
        if p[i]==min(p[i-2:i+3]) and p[i]<price:below.append(p[i])
        if p[i]==max(p[i-2:i+3]) and p[i]>price:above.append(p[i])
    support=max(below) if below else None
    if support and buffer>0:
        low=support;high=support+.5*buffer;stop=support-1.5*buffer
        targets=[v for v in above if v>max(high,price)];target=min(targets) if targets else None
        rr=(target-high)/(high-stop) if target and 0<stop<high else None
        a['levels']=dict(buyLow=low,buyHigh=high,spotStop=stop if stop>0 else None,spotTarget=target,rr=rr)
        if not a['spotBlocks']:
            if a['score']>=65 and ind['trend']>=62 and low<=price<=high and rr is not None and rr>=1.5:a['spotAction']='분할매수 검토'
            else:a['spotAction']='신규 매수 대기' if ind['trend']<40 else '눌림목·조건 대기'
    else:a['spotBlocks'].append('현물 일별 가격에서 확인된 지지 구간 부족')
    return a
def observed_change(history,symbol,key,stamp):
    target=datetime.fromisoformat(stamp)-timedelta(hours=24)
    candidates=[r for r in history if r['symbol']==symbol and number(r.get(key)) is not None and 0<=(target-datetime.fromisoformat(r['at'])).total_seconds()<=7200]
    return max(candidates,key=lambda r:r['at'])[key] if candidates else None
def assess(e,btc,now):
    ind=indicators(e['history']);s=e.get('spot') or {};p=e.get('perp') or {};u=e.get('supply') or {};book=e.get('book') or {}
    so=fresh(s.get('at'),now) and (s.get('price') or 0)>0;po=fresh(p.get('at'),now) and (p.get('mark') or 0)>0 and not p.get('delisted')
    ho=bool(ind) and fresh(e['history'][-1]['date']+'T23:59:59+00:00',now,36)
    circ=u.get('circulating');total=u.get('total');cap=s.get('marketCap');fdv=s.get('fdv')
    supply_ok=so and circ is not None and total is not None and 0<circ<=total*1.0001
    floating=min(1,circ/total) if supply_ok else None;fdvr=fdv/cap if cap and fdv else None
    supply_score=clamp(100*floating-max(fdvr-1,0)*15) if floating is not None and fdvr is not None else None
    liq=clamp(25*math.log10(max(s.get('volume24h') or 0,1)/100000)) if so and s.get('volume24h') is not None else None
    components=dict(trend=ind['trend'] if ho else None,liquidity=liq,supply=supply_score,bitcoin=btc['trend'] if btc else None)
    weights=dict(trend=.4,liquidity=.2,supply=.2,bitcoin=.2);coverage=sum(weights[k] for k,v in components.items() if v is not None)
    score=round(sum(v*weights[k] for k,v in components.items() if v is not None)/coverage) if coverage else None
    sb=[];pb=[];levels={};ls=ss=None
    if e.get('macroState') in ('unknown','risk'):sb.append('미국 금융여건 위험·자료 확인 필요');pb.append('미국 금융여건 위험·자료 확인 필요')
    if btc is None:sb.append('BTC 시장 방향 확인 필요');pb.append('BTC 시장 방향 확인 필요')
    if not ho:sb.append('최신 완료 일봉 60개 이상 필요');pb.append('최신 완료 일봉 확인 필요')
    if not so:sb.append('현물 가격 갱신 확인 필요')
    if not supply_ok or fdvr is None:sb.append('유통·발행량·FDV 자료 확인 필요')
    if supply_score is not None and supply_score<40:sb.append('낮은 유통 비율·희석 위험 검토 필요')
    if (liq or 0)<50:sb.append('현물 거래대금 부족')
    if not po:pb.append('선물 가격·상장 상태 확인 필요')
    if not (fresh(book.get('at'),now) and book.get('spread') is not None and 0<=book['spread']<=.001):pb.append('호가·스프레드 확인 필요')
    if (p.get('volume24h') or 0)<1e7 or (p.get('openInterestUSD') or 0)<1e6:pb.append('선물 유동성 부족')
    if p.get('fundingHourly') is None:pb.append('펀딩 자료 확인 필요')
    if p.get('premium') is None or abs(p['premium'])>.01:pb.append('마크·오라클 괴리 확인 필요')
    if ind and ind['volatility']>1.5:pb.append('일별 가격 변동성 과다')
    if so and po and abs(s['price']/p['mark']-1)>.03:sb.append('현물·선물 가격 차이 큼');pb.append('가격 출처 간 차이 큼')
    if ho and po:
        px=p['mark'];support=min(r['low'] for r in e['history'][-20:]);resistance=max(r['high'] for r in e['history'][-20:]);atr=ind['atr']
        stopL=support-.5*atr;stopS=resistance+.5*atr;targetL=resistance if resistance>px else None;targetS=support if support<px else None
        rrL=(targetL-px)/(px-stopL) if targetL and 0<stopL<px else None;rrS=(px-targetS)/(stopS-px) if targetS and stopS>px else None
        levels=dict(longStop=stopL if stopL>0 else None,longTarget=targetL,shortStop=stopS,shortTarget=targetS,rrLong=rrL,rrShort=rrS,spotStop=stopL*s['price']/px if so and stopL>0 else None,spotTarget=targetL*s['price']/px if so and targetL else None)
        funding=p.get('fundingHourly');premium=p.get('premium')
        if funding is not None and premium is not None:
            ls=round(clamp(ind['trend']-max(funding,0)*24*3000-abs(premium)*1000));ss=round(clamp(100-ind['trend']-max(-funding,0)*24*3000-abs(premium)*1000))
            oi=e.get('oiChange24h');change=p.get('return24h')
            if oi is not None and change is not None and oi>.1:ls=round(clamp(ls+(5 if change>0 else -5)));ss=round(clamp(ss+(5 if change<0 else -5)))
    perp_action='관망';spot_action='관망'
    if not pb:
        if ls is not None and ls>=65 and (levels.get('rrLong') or 0)>=1.5:perp_action='롱 조건 후보'
        elif ss is not None and ss>=65 and (levels.get('rrShort') or 0)>=1.5:perp_action='숏 조건 후보'
        else:pb.append('추세·비용·손익비 동시 충족 대기')
    if not sb:
        if score>=65 and ho and ind['trend']>=62 and (levels.get('rrLong') or 0)>=1.5:spot_action='분할매수 검토'
        elif ho and ind['trend']<40:spot_action='신규 매수 대기'
        else:spot_action='눌림목·조건 대기'
    return dict(indicators=ind,score=score,coverage=round(coverage*100),components=components,floatRatio=floating,fdvRatio=fdvr,spotAction=spot_action,perpAction=perp_action,longScore=ls,shortScore=ss,spotBlocks=sb,perpBlocks=pb,levels=levels)
def build(root=ROOT):
    now=datetime.now(timezone.utc);stamp=now.isoformat();millis=int(now.timestamp()*1000);directory=root/'crypto';directory.mkdir(exist_ok=True)
    old=json.loads((directory/'latest.json').read_text()) if (directory/'latest.json').exists() else {'coins':{}}
    observations=json.loads((directory/'observations.json').read_text()) if (directory/'observations.json').exists() else []
    errors=[];markets={};contexts={}
    try:markets={r['id']:r for r in request('https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids='+','.join(COINS.values())+'&sparkline=false')}
    except Exception as ex:errors.append('CoinGecko: '+str(ex))
    try:
        meta,ctx=request(HL,{'type':'metaAndAssetCtxs'});contexts={a['name']:(a,c) for a,c in zip(meta['universe'],ctx)}
    except Exception as ex:errors.append('Hyperliquid: '+str(ex))
    def collect(item):
        symbol,cg=item;prior=old['coins'].get(symbol,{});e=dict(symbol=symbol,id=cg,name=prior.get('name',symbol),history=prior.get('history',[]),spotHistory=prior.get('spotHistory',[]),spot=prior.get('spot'),supply=prior.get('supply'),perp=prior.get('perp'),book=prior.get('book'),errors=[])
        m=markets.get(cg)
        if m and str(m.get('symbol','')).upper()==symbol:
            e['name']=m['name'];e['spot']=dict(price=number(m.get('current_price')),marketCap=number(m.get('market_cap')),fdv=number(m.get('fully_diluted_valuation')),volume24h=number(m.get('total_volume')),at=m.get('last_updated'))
            e['supply']=dict(circulating=number(m.get('circulating_supply')),total=number(m.get('total_supply')),maximum=number(m.get('max_supply')))
        # Daily history is cached until the next UTC day; failed refreshes retain its own timestamps.
        last_point=(e['spotHistory'][-1].get('at') if e['spotHistory'] else '') or ''
        if not last_point.startswith(now.date().isoformat()):
            try:e['spotHistory']=spot_points(request('https://api.coingecko.com/api/v3/coins/'+cg+'/market_chart?vs_currency=usd&days=365&interval=daily'),now) or e['spotHistory']
            except Exception as ex:e['errors'].append('현물 일별 가격: '+str(ex))
        if symbol in contexts:
            a,c=contexts[symbol];mark=number(c.get('markPx'));oi=number(c.get('openInterest'));oracle=number(c.get('oraclePx'));prev=number(c.get('prevDayPx'))
            e['perp']=dict(mark=mark,oracle=oracle,fundingHourly=number(c.get('funding')),openInterest=oi,openInterestUSD=oi*mark if oi is not None and mark else None,volume24h=number(c.get('dayNtlVlm')),premium=mark/oracle-1 if mark and oracle else None,return24h=mark/prev-1 if mark and prev else None,at=stamp,delisted=bool(a.get('isDelisted')))
            try:e['history']=candles(request(HL,{'type':'candleSnapshot','req':{'coin':symbol,'interval':'1d','startTime':millis-1460*86400000,'endTime':millis}}),millis) or e['history']
            except Exception as ex:e['errors'].append('일봉: '+str(ex))
            try:
                b=request(HL,{'type':'l2Book','coin':symbol});bid=number(b['levels'][0][0]['px']);ask=number(b['levels'][1][0]['px'])
                e['book']=dict(spread=(ask-bid)/((ask+bid)/2),at=datetime.fromtimestamp(b['time']/1000,timezone.utc).isoformat(),bid=bid,ask=ask)
            except Exception as ex:e['errors'].append('호가: '+str(ex))
        else:e['errors'].append('거래소 지원·최신 메타데이터 확인 필요')
        for key,out,value,source in [('circulating','supplyChange24h',(e.get('supply') or {}).get('circulating'),e.get('spot') or {}),('openInterest','oiChange24h',(e.get('perp') or {}).get('openInterest'),e.get('perp') or {})]:
            previous=observed_change(observations,symbol,key,stamp)
            e[out]=value/previous-1 if value is not None and previous and fresh(source.get('at'),now) else None
        return symbol,e
    with ThreadPoolExecutor(3) as pool:entries=dict(pool.map(collect,COINS.items()))
    now=datetime.now(timezone.utc);stamp=now.isoformat()
    btc=indicators(entries['BTC']['history']) if entries['BTC']['history'] and fresh(entries['BTC']['history'][-1]['date']+'T23:59:59+00:00',now,36) else None
    mp=root/'market/latest.json';macro=json.loads(mp.read_text()) if mp.exists() else {}
    state=(macro.get('credit') or {}).get('status','unknown') if fresh(macro.get('generatedAt'),now,96) else 'unknown'
    btc_spot=indicators(spot_rows(entries['BTC'])) if entries['BTC']['spotHistory'] and fresh(entries['BTC']['spotHistory'][-1]['at'],now,36) else None
    for symbol,e in entries.items():
        e['macroState']=state;e['analysis']=assess(e,btc,now);ind=e['analysis']['indicators'];px=(e.get('perp') or {}).get('mark')
        e['predictions']={str(h):forecast(px,ind,h) for h in (30,120,365)} if px and ind else {}
        e['backtest']={str(h):backtest(e['history'],h) for h in (30,120,365)}
        e['spotAnalysis']=spot_assess(e,btc_spot,now);sind=e['spotAnalysis']['indicators'];spx=(e.get('spot') or {}).get('price')
        e['spotPredictions']={str(h):forecast(spx,sind,h) for h in (30,120,365)} if spx and sind else {}
        e['spotBacktest']={str(h):backtest(spot_rows(e),h) for h in (30,120,365)}
        obs=dict(symbol=symbol,at=stamp)
        if fresh((e.get('spot') or {}).get('at'),now):obs['circulating']=(e.get('supply') or {}).get('circulating')
        if fresh((e.get('perp') or {}).get('at'),now):obs['openInterest']=(e.get('perp') or {}).get('openInterest')
        if len(obs)>2:observations.append(obs)
    observations=[r for r in observations if age_hours(r['at'],now)<=840]
    payload=dict(schemaVersion=1,model='crypto-rules-v1',generatedAt=stamp,coins=entries,errors=errors,macro=dict(status=state,generatedAt=macro.get('generatedAt'),news=macro.get('news',[])[:3]))
    atomic_json(directory/'latest.json',payload);atomic_json(directory/'observations.json',observations)
    print('Crypto:',len(entries),'coins;',sum(bool(e['history']) for e in entries.values()),'histories;',errors,flush=True)
    return payload
if __name__=='__main__':build()
