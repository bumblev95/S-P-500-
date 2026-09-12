'use strict';
const assert=require('node:assert/strict'),E=require('./leverage_engine.cjs'),M=require('./leverage_methods.cjs'),R=require('./research_leverage.cjs');
const start=Date.UTC(2022,0,1),method={id:'fixture',kind:'단타'},policy={id:'margin25',margin:.25};
function fixture(candles,signal={},funding=new Map()){
 const rows=candles.map((r,i)=>({t:start+i*M.STEP,end:start+(i+1)*M.STEP-1,open:r[0],high:r[1],low:r[2],close:r[3],volume:100000}));
 const q={at:rows[0].end,side:1,price:100,stop:90,exit:'vwap',target:null,rank:1,...signal};
 const features=Object.fromEntries(['atr','ema20','ema50','ema200','daily10','daily20'].map(k=>[k,Float64Array.from(rows,()=>1)]));
 return {start,symbols:{TEST:{rows,offset:0,funding,prepared:{events:{fixture:new Map([[0,q]])},features}}}};
}
const run=(d,options={},p=policy,l=5)=>E.evaluate(d,method,p,l,start,d.symbols.TEST.rows.at(-1).end,{fee:0,slip:0,...options});
const near=(a,b)=>assert(Math.abs(a-b)<1e-7,`${a} != ${b}`);
// $2,500 isolated margin *5 = $12,500 notional =>125 units. +$10 yields $1,250.
let r=run(fixture([[100,100,100,100],[100,110,99,110]]));near(r.equity,11250);near(r.averageEntryExposure,1.25);assert.equal(r.trades,1);
r=run(fixture([[100,100,100,100],[100,101,90,90]],{side:-1,stop:110}));near(r.equity,11250);
// Both target and stop crossed: fill stop, not the favorable target.
r=run(fixture([[100,100,100,100],[100,115,85,105]],{target:110}));near(r.equity,8750);assert.equal(r.closed[0].reason,'stop');
// Gap beyond isolated liquidation loses that margin only, and keeps free collateral.
r=run(fixture([[100,100,100,100],[100,101,99,100],[70,75,65,70]]));near(r.equity,7500);assert.equal(r.liquidations,1);
// Half at2R ($120), rest gaps through the new $113 trail and fills at$110: +$1,875.
r=run(fixture([[100,100,100,100],[100,125,95,115],[110,115,99,105]],{exit:'partial2r'}));near(r.equity,11875);
assert.equal(r.partialTrades,1);
// Fees and funding must reconcile through partial exits and released margin.
const d=fixture([[100,100,100,100],[100,101,99,100],[100,101,99,100]],{},new Map([[2,{rate:.001,estimated:0}]]));
r=run(d,{fee:.001});near(r.equity,10000-12.5-12.5-12.5);near(r.funding,12.5);
assert(r.closed.every(t=>t.entryAt>t.signalAt));
near(E.size(10000,100,98,10,{risk:.02},0,0),100);near(E.size(10000,100,98,5,{margin:.5},0,0),250);
// Carrying larger capital must rerun the volume cap, not multiply a small account curve.
const capped=fixture([[100,100,100,100],[100,110,99,110]],{liquidityQty:50});
near(run(capped,{initialEquity:20000}).equity,20500);near(run(capped).equity,10500);
// The same stop-risk budget produces equal notional at5/10x when both stop gates pass.
const equal=fixture([[100,100,100,100],[100,101,99,101]],{stop:98});
near(run(equal,{}, {id:'risk2',risk:.02},5).equity,run(equal,{}, {id:'risk2',risk:.02},10).equity);
// A low in a later year must be measured against the previous year's higher peak.
const joined=R.stitch([{minEquity:10000,peakEquity:15000,maxDrawdown:.2,curve:[{at:start+M.DAY-1,equity:12000}],closed:[]},{minEquity:7500,peakEquity:12000,maxDrawdown:.375,curve:[{at:start+2*M.DAY-1,equity:10000}],closed:[]}],start,start+2*M.DAY-1);near(joined.maxDrawdown,.5);
// More stringent maintenance invalidates a stop that would be beyond liquidation.
const gate=fixture([[100,100,100,100],[100,101,99,100]],{stop:93});assert.equal(run(gate,{},policy,10).trades,1);assert.equal(run(gate,{maintenance:.05,markBuffer:.005},policy,10).trades,0);
// Missing funding charges are explicit; timestamp jitter is normalized.
const g=E.fundingGrid(Array.from({length:96},(_,i)=>({t:start+i*M.STEP,end:start+(i+1)*M.STEP-1})),[{time:start+3,rate:.001,intervalHours:8},{time:start+16*3600000+4,rate:-.001,intervalHours:8}]);assert.equal(g.get(32).estimated,1);near(g.get(64).rate,-.001);
// Features and signals before a cutoff must be identical if all future prices change.
const bars=Array.from({length:5500},(_,i)=>{const c=100+i*.02+2*Math.sin(i/17);return {t:start+i*M.STEP,end:start+(i+1)*M.STEP-1,open:c-.1,high:c+.3,low:c-.3,close:c,volume:1000+i%100};});
const cutoff=5100,a=M.prepare(bars.slice(0,cutoff)),b=M.prepare(bars.map((r,i)=>i<cutoff?r:{...r,open:r.open*10,high:r.high*10,low:r.low*10,close:r.close*10}));
for(const m of M.METHODS)assert.deepEqual([...a.events[m.id]],[...b.events[m.id]].filter(([i])=>i<cutoff));
for(const k of Object.keys(a.features))assert.deepEqual(a.features[k],b.features[k].slice(0,cutoff));
// Annual selection cannot select a spectacular result that fails the drawdown gate.
const rows=[{method:'bad',policy:'risk4',leverage:10,trades:100,return:5,maxDrawdown:.8,stress:{return:3}},{method:'ok',policy:'risk2',leverage:5,trades:30,return:.2,maxDrawdown:.1,stress:{return:.1}}];assert.equal(R.choose(rows).method,'ok');
console.log('PASS leverage accounting, long/short, same-bar priority, isolated gap loss, partial close, fees/funding, sizing, maintenance gate, funding gaps and prefix invariance.');
