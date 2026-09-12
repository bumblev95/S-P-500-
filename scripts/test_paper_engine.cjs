'use strict';
const assert=require('node:assert/strict'),P=require('./paper_engine.cjs'),S=require('../assets/simulation-signals.js');
const STEP=900000,base=Date.UTC(2026,0,1),now=base+120*STEP;
function rows(n=120){return Array.from({length:n},(_,i)=>({t:base+i*STEP,end:base+(i+1)*STEP-1,open:100,high:100.2,low:99.8,close:100,volume:100}));}
function market(rs=rows()){return {crypto:{BTC:{frames:{'15m':rs,'1h':[]},funding:[]},ETH:{frames:{'15m':structuredClone(rs),'1h':[]},funding:[]}}};}
const provider=(symbol,rs)=>symbol==='BTC'&&rs.at(-1).t===base+65*STEP?{side:'long',pattern:'retest',reason:'test',at:rs.at(-1).end,price:100,stop:99,target:102,atr:1,rank:1,holdBars:8}:{side:null,at:rs.at(-1).end};
let rs=rows();rs[66]={...rs[66],high:103,low:98};
let a=P.run(P.create('crypto',now),market(rs),{mode:'replay',now,provider});
assert.equal(a.trades.length,1);assert.equal(a.trades[0].entryAt,rs[66].t);assert(a.trades[0].orderCreatedAt<a.trades[0].entryAt);assert(a.trades[0].exitReason.includes('同')===false);assert(a.trades[0].exitReason.includes('동시'));assert(a.trades[0].net<0);assert(a.cash<10000);
// Same-bar results must never be used to create an earlier entry.
const prefix=P.run(P.create('crypto',base+66*STEP),market(rs),{mode:'replay',now:base+66*STEP,provider});assert.equal(prefix.trades.length,0);assert.equal(prefix.pending.length,1);
const changed=structuredClone(rs);changed[66].high=999;
const prefix2=P.run(P.create('crypto',base+66*STEP),market(changed),{mode:'replay',now:base+66*STEP,provider});assert.deepEqual(prefix.events,prefix2.events);
// Gap stops execute at the adverse opening price, not a stale stop price.
rs=rows();rs[67]={...rs[67],open:95,high:96,low:94,close:95};
a=P.run(P.create('crypto',now),market(rs),{mode:'replay',now,provider});assert(a.trades[0].exit<95);assert(a.trades[0].exitReason.includes('갭'));
// A new forward account never retroactively trades the downloaded history.
let live=P.run(P.create('crypto',now),market(),{mode:'forward',now,provider});assert.equal(live.trades.length,0);assert.equal(live.positions.length,0);assert.equal(live.events.length,0);assert.equal(live.equity,10000);
const latestProvider=(symbol,r)=>symbol==='BTC'?{side:'short',pattern:'candle',reason:'test',at:r.at(-1).end,price:100,stop:101,target:98,atr:1,rank:1,holdBars:8}:{side:null};
live=P.run(P.create('crypto',now+1000),market(),{mode:'forward',now:now+1000,provider:latestProvider});assert.equal(live.pending.length,1);
const repeat=P.run(live,market(),{mode:'forward',now:now+2000,provider:latestProvider});assert.deepEqual(repeat.events,live.events);
// A candle that had already opened when the signal was recorded cannot fill it.
const next=rows(122);next[121]={...next[121],low:97,high:100.2};
let filled=P.run(live,market(next),{mode:'forward',now:base+122*STEP,provider:()=>({side:null})});
assert.equal(filled.trades.length,1);assert.equal(filled.trades[0].entryAt,next[121].t);assert(filled.trades[0].net>0);assert(filled.trades[0].side==='short');
const rerun=P.run(filled,market(next),{mode:'forward',now:base+122*STEP+1000,provider:()=>({side:null})});assert.deepEqual(rerun.trades,filled.trades);assert.equal(rerun.events.length,filled.events.length);
// One-times collateral and risk budget, including both fees and stop slippage.
const account=P.create('crypto',now),order={id:'one',symbol:'BTC',side:'long',pattern:'x',price:100,stop:99,target:102,atr:1,at:0,createdAt:0,holdBars:8};
assert.equal(P.enter(account,order,rows()[0],P.CONFIG.crypto,now),null);
assert(account.cash>=0);assert(account.positions[0].margin<=10000/3);const pos=account.positions[0];P.close(account,pos,99,1,'test',P.CONFIG.crypto,now);assert(10000-account.cash<=50);
// Opening capital cannot come from a target reached later in the same bar.
let empty=P.create('crypto',now);empty.lastProcessed=rows()[65].t;empty.marks={BTC:100};empty.benchmark={qty:100,price:100};empty.curve=[];empty.cash=0;empty.positions=[{...pos,id:'held',qty:100,margin:10000,entry:100,entryFee:0,entryAt:rows()[65].t,stop:90,target:101,funding:0,fundingThrough:rows()[65].end,bars:0,holdBars:8}];empty.pending=[{...order,id:'eth',symbol:'ETH',notBefore:rows()[66].t,expires:rows()[67].t}];
const rt=rows(67);rt[66].high=102;
const noReuse=P.run(empty,market(rt),{mode:'forward',now:base+67*STEP,provider:()=>({side:null})});assert.equal(noReuse.positions.length,0);assert(!noReuse.events.some(e=>e.type==='entry'));
// Funding sign and missing-rate accounting remain visible.
let fa=P.create('crypto',now);const fp={entryAt:base,fundingThrough:base,qty:2,side:'short',funding:0};P.funding(fa,fp,base+3600000,{funding:[{time:base+3600000,rate:.001}]},100);assert.equal(fp.funding,-.2);assert.equal(fa.cash,10000.2);
P.funding(fa,fp,base+7200000,{funding:[]},100);assert.equal(fa.estimatedFundingHours,1);assert(fa.warnings.length);
const jitter=P.create('crypto',now),jp={entryAt:base,fundingThrough:base,qty:2,side:'long',funding:0};
P.funding(jitter,jp,base+3600000+100,{funding:[{time:base+3600000+44,rate:.001}]},100);assert.equal(jp.funding,.2);assert.equal(jitter.estimatedFundingHours,0);
// Actual detector cannot read a still-forming higher-timeframe bar.
const signal=S.crypto(rows(),[]);assert.equal(signal.side,null);
assert.throws(()=>P.run({...P.create('crypto',now),version:'old'},market(),{now}),/version/);
console.log('Paper accounts: next-bar fills, future-data isolation, gap and dual-hit stops, costs, funding, 1x collateral, idempotence and capital chronology passed');
