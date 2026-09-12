'use strict';
const assert=require('node:assert/strict'),P=require('./paper_engine.cjs');
const cfg=P.LEVERAGED,t=1780000000000,bar={t,end:t+899999,open:100,high:100.5,low:99.5,close:100,volume:100};
const order={id:'risk',symbol:'BTC',side:'long',pattern:'candle',reason:'fixture',price:100,stop:99,target:102,atr:1,at:t-1,createdAt:t-1,holdBars:8};
function account(){const a=P.create('crypto',t,'leverage5x3x');a.marks={BTC:100,ETH:100,SOL:100};return a;}
for(const [symbol,leverage] of [['BTC',5],['ETH',3],['SOL',3]]){
 const a=account();assert.equal(P.enter(a,{...order,symbol},bar,cfg,t),null);const p=a.positions[0];
 assert.equal(p.leverage,leverage);assert(Math.abs(p.margin*leverage-p.qty*p.entry)<1e-8);assert(Math.abs(p.entryFee-p.qty*p.entry*cfg.fee)<1e-8);
 assert(p.riskBudget<=50);assert(a.cash>=0);assert(p.margin<=2000);assert(p.stop>p.liquidation);
 const before=P.equity(a),cash=a.cash;P.funding(a,p,t+3600000,{funding:[{time:t+3600000,rate:.001}]},100);
 assert.equal(a.cash,cash);assert(Math.abs(P.equity(a)-(before-p.funding))<1e-8);
 P.close(a,p,99,t+3600000,'fixture',cfg,t);assert(Math.abs(a.cash-10000-a.trades[0].net)<1e-8);
}
const daily=account();P.riskState(daily,t,cfg);daily.cash=9799;
assert.match(P.enter(daily,order,bar,cfg,t),/하루 손실/);
assert.equal(P.enter(daily,order,{...bar,t:t+86400000},cfg,t+86400000),null);
const dd=account();P.riskState(dd,t,cfg);dd.cash=8999;
assert.match(P.enter(dd,order,bar,cfg,t),/10%/);dd.cash=10000;
assert.match(P.enter(dd,order,{...bar,t:t+86400000},cfg,t),/10%/);
const streak=account();for(let i=0;i<3;i++){assert.equal(P.enter(streak,{...order,id:'loss'+i},{...bar,t:t+i*1000},cfg,t),null);P.close(streak,streak.positions[0],99,t+i*1000+1,'fixture',cfg,t);}
assert.match(P.enter(streak,order,{...bar,t:t+4000},cfg,t),/6시간/);
assert.equal(P.enter(streak,order,{...bar,t:streak.cooldownUntil+1},cfg,t),null);
const caps=account();for(const symbol of ['BTC','ETH','SOL'])P.enter(caps,{...order,id:symbol,symbol},bar,cfg,t);
assert(caps.positions.reduce((s,p)=>s+p.riskBudget,0)<=150);
assert(caps.positions.reduce((s,p)=>s+p.margin,0)<=4000);
function gap(side,open){const a=account(),q={...order,side,stop:side==='long'?99:101,target:side==='long'?102:98};P.enter(a,q,bar,cfg,t);a.lastProcessed=t;a.startedAt=t;a.benchmark={qty:100};a.curve=[];
 const next={...bar,t:t+900000,end:t+1799999,open,high:Math.max(open,100.1),low:Math.min(open,99.9),close:open};
 return P.run(a,{crypto:{BTC:{frames:{'15m':[bar,next]},funding:[]}}},{now:t+1800000,provider:()=>({side:null})});}
for(const [side,open] of [['long',70],['short',140]]){const a=gap(side,open);assert.equal(a.positions.length,0);assert.match(a.trades[0].exitReason,/격리 청산/);assert(a.cash>=0);assert(Math.abs(P.equity(a)-10000-a.trades[0].net)<1e-7);}
// A continuous candle crossing both boundaries reaches the closer stop first.
const continuous=account();P.enter(continuous,order,bar,cfg,t);continuous.lastProcessed=t;continuous.startedAt=t;continuous.benchmark={qty:100};
const crossed={...bar,t:t+900000,end:t+1799999,low:70,high:103};
const stopped=P.run(continuous,{crypto:{BTC:{frames:{'15m':[bar,crossed]},funding:[]}}},{now:t+1800000,provider:()=>({side:null})});
assert.match(stopped.trades[0].exitReason,/손절/);assert(!stopped.trades[0].exitReason.includes('격리 청산'));
// Completed-hour feature context must ignore a still-forming future candle.
const R=require('./pattern_research_data.cjs');
const history=Array.from({length:80},(_,i)=>({...bar,t:t+i*900000,end:t+(i+1)*900000-1,open:100+i*.1,close:100+i*.1,high:101+i*.1,low:99+i*.1}));
const last=history.at(-1).end,hours=Array.from({length:65},(_,i)=>({...bar,t:last-(65-i)*3600000+1,end:last-(64-i)*3600000}));
assert.deepEqual(R.features(history,hours,'BTC',order),R.features(history,[...hours,{...bar,t:last+1,end:last+3600000,close:1e9}],'BTC',order));
assert.throws(()=>P.run({...account(),profileVersion:'changed'},{},{now:t}),/version/);
console.log('Leveraged accounts: notional fees, isolated funding, risk sizing, daily stop, drawdown latch, loss cooldown, gap liquidation and ledger reconciliation passed');
