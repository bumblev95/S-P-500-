'use strict';
const assert=require('node:assert/strict'),C=require('./momentum_cpd.cjs'),P=require('./paper_engine.cjs');
// Stable noise followed by a large persistent shift must move posterior mass
// to short run lengths. Posterior values must remain normalized and finite.
const d=new C.Detector(.0001);let before,peak=0;
for(let i=0;i<240;i++){before=d.update(.001*Math.sin(i*1.7));assert(Math.abs(d.states.reduce((s,v)=>s+v.p,0)-1)<1e-12);}
for(let i=0;i<6;i++)peak=Math.max(peak,d.update(.08+.001*Math.sin(i)).recentProbability);
assert(peak>.5&&peak>before.recentProbability,'Detector must recognize a known mean shift');
const memory={},q={side:'short',price:100,atr:1,stop:102.5,target:null,exitLong:true,exitShort:false,trailLong:97.5,trailShort:102.5,holdBars:2880,rank:1,at:0};
const v=C.overlay(q,{ready:true,recentProbability:.9},2,0,memory);
assert.equal(v.side,null);assert(v.exitShort);assert.equal(v.stop,q.stop);
assert.equal(C.overlay(q,{ready:true,recentProbability:0},0,C.H4,memory).side,null);
assert.equal(C.overlay(q,{ready:true,recentProbability:0},0,6*C.H4,memory).side,'short');
const start=Date.UTC(2024,0,1),rows=Array.from({length:8000},(_,i)=>{
 const close=100*Math.exp(i*.00001+.002*Math.sin(i/30));return {t:start+i*900000,end:start+(i+1)*900000-1,open:close,close,high:close+.1,low:close-.1,volume:1};
});
const config={start:start+35*C.DAY,end:rows.at(-1).end,trainingStart:start,trainingEnd:start+14*C.DAY};
const full=C.signals(rows,config),short=C.signals(rows.slice(0,6500),{...config,end:rows[6499].end});
assert.deepEqual(full.prior,short.prior);assert(short.maps.size>100);
for(const [at,s] of short.maps)assert.deepEqual(full.maps.get(at),s,'Future observations changed a past decision');
const altered=rows.map(r=>r.end>=config.start?{...r,close:r.close*2,high:r.high*2,low:r.low*2,open:r.open*2}:r);
assert.deepEqual(C.signals(altered,config).prior,full.prior,'Evaluation prices changed calibration');
assert.throws(()=>C.signals(rows,{...config,trainingEnd:config.end}),/leaks/);
// CPD exit generated at one close settles at the next open, not inside its bar.
const bars=rows.slice(0,4).map(r=>({...r,open:100,close:100,high:100.1,low:99.9}));
const initial={...q,at:bars[0].end,pattern:'momentum14_cpd'};
const provider=(s,rs)=>rs.at(-1).end===bars[0].end?initial:rs.at(-1).end===bars[1].end?{...v,at:bars[1].end}:{side:null};
const account=P.run(P.create('crypto',start,'trendResearch'),{crypto:{BTC:{frames:{'15m':bars},funding:[]}}},{mode:'replay',startAt:start,now:bars.at(-1).end+1,provider});
assert.equal(account.trades.length,1);assert.equal(account.trades[0].exitAt,bars[2].t);
// Market windowing must keep the next settlement timestamp so the final hours
// of a period are not spuriously charged as missing hourly funding.
const R=require('./research_momentum_cpd.cjs'),E=require('./research_trend_methods.cjs');
const funding=[{time:start,rate:.0001,intervalHours:8},{time:start+8*3600000,rate:.0001,intervalHours:8}];
const fundingMarket={crypto:{BTC:{frames:{'15m':rows.slice(0,20).map(r=>({...r,open:100,close:100,high:100.1,low:99.9}))},funding,fundingSchedule:'published'}}};
const initialMap={BTC:new Map([[bars[0].end,initial]])},end=fundingMarket.crypto.BTC.frames['15m'].at(-1).end;
const original=E.evaluate(fundingMarket,initialMap,start,end),windowed=E.evaluate(R.sliceMarket(fundingMarket,start,end),initialMap,start,end);
assert.equal(windowed.funding,original.funding);assert.equal(windowed.estimatedFundingHours,0);assert.equal(windowed.equity,original.equity);
console.log('CPD detection, posterior normalization, cooldown, unchanged stop, calibration isolation, prefix invariance and next-open exit passed');
