const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),E=require('../assets/perp-engine.js');
const now=Date.parse('2026-09-11T23:00:00Z')+1000;
function fixture(){
 let n=1075,p=100;const rnd=()=>((n=Math.imul(n,1664525)+1013904223>>>0)/4294967296),frames={};
 for(const tf of Object.keys(E.MS)){const ms=E.MS[tf],end=Math.floor(now/ms)*ms;frames[tf]=Array.from({length:240},(_,i)=>{const open=p;p=Math.max(1,p+.12+(rnd()-.5)*1.6);return {t:end-(240-i)*ms,end:end-(239-i)*ms-1,open,close:p,high:Math.max(open,p)+.15,low:Math.min(open,p)-.15,volume:100+50*rnd()};});}
 return {symbol:'BTC',frames,receivedAt:now,quoteAt:now,bookAt:now,quote:{mark:frames['5m'].at(-1).close,funding:.000001,premium:0,oiUSD:1e8,volume24h:1e9},book:{spread:.0001}};
}
const s=fixture(),long=E.analyze(s,'5m',now);assert.equal(long.action,'롱 조건 충족');assert(long.long.rr>=1.5);assert(long.long.target>long.long.entry&&long.long.stop<long.long.entry);
const short=structuredClone(s);for(const rows of Object.values(short.frames))for(const r of rows){const high=260-r.low,low=260-r.high;r.open=260-r.open;r.close=260-r.close;r.high=high;r.low=low;}short.quote.mark=260-s.quote.mark;
assert.equal(E.analyze(short,'5m',now).action,'숏 조건 충족');
assert.equal(E.analyze(s,'5m',now+91000).action,'관망');
for(const mutate of [x=>x.frames['5m'].splice(200,1),x=>x.quote.funding=null,x=>x.book.spread=.01,x=>x.quote.mark*=1.1,x=>x.error='offline',x=>x.frames['15m']=short.frames['15m'],x=>x.quote.oiUSD=100]){const copy=structuredClone(s);mutate(copy);assert.equal(E.analyze(copy,'5m',now).action,'관망');}
const raw=s.frames['5m'].map(r=>({s:'BTC',i:'5m',t:r.t,T:r.end,o:r.open,h:r.high,l:r.low,c:r.close,v:r.volume}));
const forming={...raw.at(-1),t:Math.floor(now/300000)*300000,T:Math.floor(now/300000)*300000+299999};
assert.equal(E.candles([...raw,forming],'5m',now,'BTC').length,240);
assert.deepEqual(E.candles([{...raw[0],v:null},{...raw[0],i:'15m'},{...raw[0],s:'ETH'}],'5m',now,'BTC'),[]);
const ind=E.indicators(s.frames['5m'],'5m'),pattern=E.detect(s.frames['5m'],ind),zero=E.levels(s.frames['5m'],ind,pattern,'long',0,300000),costly=E.levels(s.frames['5m'],ind,pattern,'long',.002,300000);assert(costly.rr<zero.rr);
// Exercise the actual page loader and interactions without requiring network access in CI.
const nodes=new Map(),node=id=>nodes.get(id)||nodes.set(id,{innerHTML:'',textContent:'',value:'BTC',disabled:false,events:{},addEventListener(k,f){this.events[k]=f;}}).get(id);
const buttons=['5m','15m','1d'].map(tf=>({dataset:{tf},addEventListener(k,f){this[k]=f},setAttribute(){}})),timers=[];let clock=now,fail=false;
class Clock extends Date{constructor(...args){super(...(args.length?args:[clock]))}static now(){return clock}}
const context={PerpEngine:{...E,analyze:(s,tf)=>E.analyze(s,tf,clock)},window:{innerWidth:390},document:{hidden:false,getElementById:node,querySelectorAll:()=>buttons,addEventListener(){}},Date:Clock,Intl,console,AbortController,setTimeout(){return 1},clearTimeout(){},setInterval(f){timers.push(f)},fetch:async(url,args)=>{
 assert.equal(url,'https://api.hyperliquid.xyz/info');if(fail)throw Error('offline');const b=JSON.parse(args.body);let result;
 if(b.type==='metaAndAssetCtxs')result=[{universe:[{name:'BTC'}]},[{markPx:s.quote.mark,oraclePx:s.quote.mark,funding:.000001,openInterest:1e8/s.quote.mark,dayNtlVlm:1e9}]];
 else if(b.type==='l2Book')result={time:now,levels:[[{px:s.quote.mark-.001}],[{px:s.quote.mark+.001}]]};
 else result=s.frames[b.req.interval].map(r=>({s:'BTC',i:b.req.interval,t:r.t,T:r.end,o:r.open,h:r.high,l:r.low,c:r.close,v:r.volume}));
 return {ok:true,status:200,json:async()=>result};
}};
vm.runInNewContext(fs.readFileSync('assets/perp-page.js','utf8'),context);
setImmediate(()=>{
 let html=node('app').innerHTML;assert(html.includes('롱 조건 충족'));assert(html.includes('손절 기준'));assert(!/NaN|Infinity|undefined/.test(html));
 for(const b of buttons){b.click();assert(node('app').innerHTML.includes(b.dataset.tf==='1d'?'일봉':b.dataset.tf==='15m'?'15분봉':'5분봉'));}
 buttons[0].click();clock+=120000;timers[1]();assert(node('app').innerHTML.includes('관망'));assert(!node('app').innerHTML.includes('롱 조건 충족'));
 fail=true;node('refresh').events.click();setImmediate(()=>{assert(node('app').innerHTML.includes('갱신하지 못해'));console.log('Perp: long/short candidates, stale/gap/cost guards, completed candles, 3 timeframe UI and failed refresh passed');});
});
