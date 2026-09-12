'use strict';
const assert=require('node:assert/strict'),M=require('./signal_tournament.cjs'),R=require('./research_signal_tournament.cjs'),P=require('./paper_engine.cjs');
assert.equal(M.METHODS.length,32);assert.equal(new Set(M.METHODS.map(m=>m.id)).size,32);
assert.equal(M.utStep(110,108,100,5),105);assert.equal(M.utStep(90,92,100,5),95);assert.equal(M.utStep(110,90,100,5),105);
assert.equal(M.regressionLast([2,4,6,8]),8);
const rows=[];const start=Date.UTC(2020,0,1);
for(let i=0;i<16000;i++){const price=100+10*Math.sin(i/77)+.001*i,close=100+10*Math.sin((i+1)/77)+.001*(i+1);rows.push({t:start+i*900000,end:start+(i+1)*900000-1,open:price,high:Math.max(price,close)+.3,low:Math.min(price,close)-.3,close});}
const all=M.prepare(rows),prefix=M.prepare(rows.slice(0,13000));
assert(prefix.size>100);
for(const [at,q]of prefix){assert.deepEqual(q,all.get(at),'Future candles changed a historical signal');if(q.knn.labelEnd!==null)assert(q.knn.labelEnd<=at-14400000,'kNN target crosses decision boundary');}
const row=[...all.values()].find(q=>q.families.momentum.side);assert(row);
const base=row.families.momentum,blocked=M.apply(M.METHODS.find(m=>m.id==='momentum_boost'),row,-1);
assert.equal(blocked.side,null);for(const key of ['exitLong','exitShort','trailLong','trailShort'])assert.equal(blocked[key],base[key],'Entry filter changed exit protection');
const eligible={method:'good',trades:30,return:.1,maxDrawdown:.1,expectancyR:.2,sharpe:1,stress:{return:.02}};
assert.equal(R.choose([eligible,{...eligible,method:'fake',return:10,stress:{return:-.1},sharpe:10}]),'good');assert.equal(R.choose([{...eligible,trades:0}]),'cash');
const source={frames:{'15m':rows},funding:[]},market={crypto:{BTC:source,ETH:source,SOL:source}},maps={BTC:all,ETH:all,SOL:all};
const at=rows[4000].t,to=rows.at(-1).end,cfg=P.config(P.create('crypto',at,'selectorTargets')),old=cfg.maxPositions;
const r=R.evaluate(R.sliced(market,at,to),maps,new Map(),M.METHODS.find(m=>m.id==='ut_none'),at,to);
assert(r.trades>5);assert.equal(r.maxHeld,1);assert.equal(cfg.maxPositions,old);assert(r.closed.every(t=>t.entryAt>t.signalAt));
const stress=R.evaluate(R.sliced(market,at,to),maps,new Map(),M.METHODS.find(m=>m.id==='ut_none'),at,to,true);
assert(stress.fees>0&&r.fees>0);
const noFuture={...source,frames:{'15m':rows.slice(0,8000)}};assert(R.sliced({crypto:{BTC:noFuture}},at,rows[6000].end).crypto.BTC.frames['15m'].every(r=>r.end<=rows[6000].end));
console.log('PASS: 32 recipes, UT reference cases, causal prefix and kNN labels, preserved exits, selection gates, actual next-bar fills and one-position cap.');
