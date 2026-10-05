'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),zlib=require('node:zlib');
const R=require('./backtest_top3_rankings.cjs'),T=require('../assets/technical-guide.js'),Home=require('./build_home_rankings.cjs');
function row(symbol,score,code='breakout',holding='hold',distance=0,breach=0){
 return {symbol,score,asOf:'2026-10-02',price:100,sector:'Test',distance,risk:.04,breach,volume:false,pressure:false,
 sectorUp:false,sectorDown:false,plan:{code,ts:score,holding:{code:holding}}};
}
let tests=0;function check(name,fn){fn();tests++;console.log('PASS '+name);}
check('state priority never replaced by volume/sector flags',()=>{
 const a=row('A',60,'buy'),b=row('B',100);b.volume=true;b.sectorUp=true;
 for(const m of R.METHODS)assert.equal(R.select([b,a],m).buy[0].symbol,'A');
});
check('distance only changes exact ties in tie method',()=>{
 const a=row('A',99,'breakout','hold',3),b=row('B',98,'breakout','hold',0);
 assert.equal(R.select([a,b],'tie_price_risk').buy[0].symbol,'A');
 b.score=99;assert.equal(R.select([a,b],'tie_price_risk').buy[0].symbol,'B');
});
check('missing distance or breach is never preferred',()=>{
 const a=row('A',90,'breakout','hold',null,null),b=row('B',90,'breakout','hold',1,.2);
 assert.equal(R.compare(a,b,'buy','price_risk')>0,true);
 assert.equal(R.compare(a,b,'sell','price_risk')>0,true);
});
check('daily unique nonoverlapping TOP3',()=>{
 const all=Array.from({length:10},(_,i)=>row(String.fromCharCode(65+i),i*10));
 for(const m of R.METHODS){const q=R.select(all,m);assert.equal(q.buy.length,3);assert.equal(q.sell.length,3);
 assert.equal(new Set([...q.buy,...q.sell].map(x=>x.symbol)).size,6);}
});
check('waiting candidates never create orders; all holdings still get exits',()=>{
 const a=R.newAccount({t:1,date:'2026-10-02'},'stable','baseline',1),waiting=row('A',100);
 a.positions.push({symbol:'Z',stop:1});const sell=row('Z',0,'avoid','reduce');
 R.observe(a,[waiting,sell],[waiting],'2026-10-02');
 assert.equal(a.pending.length,0);assert.equal(a.positions[0].exitPending,'reduce');
});
check('sector benchmark uses prior anchor and excludes issuer itself',()=>{
 const mk=(sector,prices)=>({sector,rows:prices.map((close,i)=>({date:'d'+i,close})),byDate:new Map(prices.map((_,i)=>['d'+i,i]))});
 const d={SPY:mk('ETF / index',[100,110]),A:mk('Tech',[100,120]),B:mk('Tech',[100,100]),C:mk('Tech',[100,130])};
 const q=R.sectorReturns(d,'d1','d0');
 assert(Math.abs(q.A-.05)<1e-12);assert(Math.abs(q.B-.15)<1e-12);
 d.A.rows.push({date:'future',close:100000});assert.deepEqual(R.sectorReturns(d,'d1','d0'),q);
});
check('next open, missing-session exclusions and sale-vs-hold costs',()=>{
 const mk=bars=>({rows:bars,byDate:new Map(bars.map((r,i)=>[r.date,i]))});
 const bars=[{date:'d0',open:100,close:100,low:99},{date:'d1',open:200,close:180,low:170},{date:'d2',open:180,close:160,low:150}];
 const d={A:mk(bars),SPY:mk(bars.map(r=>({...r,open:100,close:100,low:99})))};
 const buy=R.outcome(d,'A','d0',2,'buy'),sell=R.outcome(d,'A','d0',2,'sell');
 assert.equal(buy.entryDate,'d1');assert.equal(buy.endDate,'d2');assert(Math.abs(buy.gross+.2)<1e-12);
 assert(Math.abs(sell.avoidance-.2*(1-.0005)**2)<1e-12);
 assert.equal(R.outcome(d,'A','d1',2,'buy').excluded,'immature');
 d.A.rows[2]={...d.A.rows[2],date:'different'};
 assert.equal(R.outcome(d,'A','d0',2,'buy').excluded,'missingSession');
});
check('cached date validation is identical on valid and malformed histories',()=>{
 const F=require('./top3_cached_rule.cjs').loadCachedRule(require.resolve('../assets/technical-guide.js'));
 const rows=Array.from({length:205},(_,i)=>{const t=Date.UTC(2025,0,1+i),close=100+i*.05;
  return {date:new Date(t).toISOString().slice(0,10),t,end:t+72000000,open:close,high:close+1,low:close-1,close,signalPrice:close,volume:10000};});
 const e=R.makeEntry({rows},'TEST',204),market=R.scenarioFeed('stable',e.asOf),now=Date.parse(e.asOf+'T23:59:59Z');
 for(const malformed of [null,'invalid','2025-02-30','2025-13-01']){
  const q=JSON.parse(JSON.stringify(e));if(malformed!==null)q.history[3].date=malformed;
  assert.equal(JSON.stringify(F.plan(q,null,market,now)),JSON.stringify(T.plan(q,null,market,now)));
 }
});
if(fs.existsSync('research/history/entry-backtest-2026-10-04/prices.json.gz'))check('latest 505 baseline agrees with operating selector and future bars cannot change a prefix',()=>{
 const d=JSON.parse(zlib.gunzipSync(fs.readFileSync('research/history/entry-backtest-2026-10-04/prices.json.gz')));
 const date=d.cutoff,now=Date.parse(date+'T23:59:59Z'),all=[];
 for(const [s,v] of Object.entries(d.stocks)){
  const e=R.makeEntry(v,s,v.rows.length-1),p=T.plan(e,null,R.scenarioFeed('stable',date),now);
  all.push(R.feature(e,p,v.sector,null));
 }
 const ours=R.select(all),actual=Home.select(Object.fromEntries(all.map(q=>[q.symbol,q])),now);
 assert.deepEqual(ours.buy.map(q=>q.symbol),actual.buy.map(q=>q.symbol));
 assert.deepEqual(ours.sell.map(q=>q.symbol),actual.sell.map(q=>q.symbol));
 assert.deepEqual(ours.buy.map(q=>q.symbol),['ILMN','RVTY','FTNT']);
 assert.deepEqual(ours.sell.map(q=>q.symbol),['AON','APP','CCI']);
 const source=d.stocks.NVDA,index=source.rows.length-100;
 const before=R.makeEntry(source,'NVDA',index),plan=T.plan(before,null,R.scenarioFeed('stable',before.asOf),Date.parse(before.asOf+'T23:59:59Z'));
 for(let i=index+1;i<source.rows.length;i++)source.rows[i].close*=100;
 const after=R.makeEntry(source,'NVDA',index),again=T.plan(after,null,R.scenarioFeed('stable',after.asOf),Date.parse(after.asOf+'T23:59:59Z'));
 assert.deepEqual(after,before);assert.deepEqual(again,plan);
});
console.log(JSON.stringify({tests,passed:true}));
