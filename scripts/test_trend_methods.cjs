'use strict';
const assert=require('node:assert/strict'),T=require('./trend_methods.cjs'),P=require('./paper_engine.cjs');
const start=Date.UTC(2024,0,1),step=900000;
const rows=Array.from({length:4000},(_,i)=>({t:start+i*step,end:start+(i+1)*step-1,open:100+i*.01,close:100+i*.01,high:100.02+i*.01,low:99.98+i*.01,volume:1}));
assert.equal(T.aggregate(rows.slice(0,15)).length,0);
assert.equal(T.aggregate(rows.slice(0,16)).length,1);
assert.equal(T.aggregate(rows.slice(1,16)).length,0);
for(const method of T.METHODS){
 const prefix=T.signals(rows.slice(0,3500),method.id),full=T.signals(rows,method.id);
 assert(prefix.size>0);for(const [at,q] of prefix)assert.deepEqual(full.get(at),q,'future candles changed a past signal');
}
// Tightening at the completed bar cannot retroactively stop a position inside it.
const bars=rows.slice(0,6).map((r,i)=>({...r,open:100,close:100,high:101,low:99}));
bars[2]={...bars[2],low:97.5};bars[3]={...bars[3],low:97.5};
const q={side:'long',symbol:'BTC',at:bars[0].end,price:100,atr:1,stop:97,target:null,holdBars:100,rank:1,pattern:'fixture'};
const provider=(s,rs)=>rs.at(-1).end===q.at?q:rs.at(-1).end===bars[2].end?{side:null,trailLong:98}:{side:null};
const market={crypto:{BTC:{frames:{'15m':bars},funding:[]}}};
const a=P.run(P.create('crypto',start,'trendResearch'),market,{mode:'replay',startAt:start,now:bars.at(-1).end+1,provider});
assert.equal(a.trades.length,1);assert.equal(a.trades[0].exitAt,bars[3].end);assert(a.trades[0].exitReason.startsWith('손절'));
// A trend exit is filled at the following open, including adverse gaps.
const flip=(s,rs)=>rs.at(-1).end===q.at?q:rs.at(-1).end===bars[1].end?{side:null,exitLong:true}:{side:null};
const b=P.run(P.create('crypto',start,'trendResearch'),market,{mode:'replay',startAt:start,now:bars.at(-1).end+1,provider:flip});
assert.equal(b.trades[0].exitAt,bars[2].t);assert.equal(b.trades[0].exitReason,'4시간 추세 이탈');
console.log('Fixed trend signals: complete bars, prefix invariance, next-bar trailing stops and trend exits passed');
