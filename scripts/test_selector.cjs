'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),P=require('./paper_engine.cjs'),T=require('./trend_methods.cjs'),D=require('./selector_data.cjs');
function check(market){
 let checked=0;
 for(const [symbol,source] of Object.entries(market.crypto)){
  const rows=source.frames['15m'],maps=T.signals(rows,'momentum14'),f=D.features(source,symbol,maps);
  const samples=f.filter(r=>r.trainingSample);
  for(const pos of [10,Math.floor(samples.length/2),samples.length-50]){
   const s=samples[pos],i=s.index,expected=D.label(source,symbol,maps,i);if(!expected)continue;
   const frames={'15m':rows.slice(i,i+30*96+2)},small={...source,frames},input={crypto:{BTC:small,[symbol]:small}};
   const provider=(sym,rs)=>{const q=maps.get(rs.at(-1).end);return q?{...q,side:sym===symbol&&q.at===s.at?q.side:null}:{side:null};};
   const a=P.run(P.create('crypto',s.at,'trendResearch'),input,{mode:'replay',startAt:rows[i].t,now:frames['15m'].at(-1).end+1,provider});
   assert.equal(a.trades.length,1);
   const t=a.trades[0];assert.equal(t.exitAt,expected.labelEnd);assert.ok(Math.abs(t.net-expected.net)<1e-6,JSON.stringify({symbol,actual:t.net,expected:expected.net}));assert.equal(t.qty,expected.qty);checked++;
  }
  const cut=Math.floor(rows.length*.65),partial={...source,frames:{'15m':rows.slice(0,cut)},funding:source.funding.filter(r=>r.time<rows[cut].t)};
  const pf=D.features(partial,symbol,T.signals(partial.frames['15m'],'momentum14'));
  assert.deepEqual(pf.at(-1).x,f.find(r=>r.at===pf.at(-1).at).x,'Appending future data must not change features');
 }
 assert.equal(checked,9);console.log('PASS: 9 independent payoff labels match full shared engine; prefix-invariant features for 3 assets');
}
function targetTests(){
 const at=Date.UTC(2024,0,1),bar=(i,open,high,low,close)=>({t:at+i*900000,end:at+(i+1)*900000-1,open,high,low,close,volume:1});
 const rows=[bar(0,100,100,100,100),bar(1,100,111,99,109),bar(2,109,109,109,109)];
 const market={crypto:{BTC:{frames:{'15m':rows},funding:[]}}};
 const provider=(_,rs)=>rs.at(-1).end===rows[0].end?{at:rows[0].end,side:'long',price:100,atr:2,stop:95,target:110,rank:1,holdBars:100,pattern:'test'}:{side:null};
 let a=P.run(P.create('crypto',at,'selectorTargets'),market,{mode:'replay',startAt:at,now:rows.at(-1).end+1,provider});assert.equal(a.trades[0].exitReason,'익절 · 연구 목표');
 a=P.run(P.create('crypto',at,'trendResearch'),market,{mode:'replay',startAt:at,now:rows.at(-1).end+1,provider});assert.equal(a.trades.length,0,'Default trend must still ignore targets');
 rows[1].low=94;a=P.run(P.create('crypto',at,'selectorTargets'),market,{mode:'replay',startAt:at,now:rows.at(-1).end+1,provider});assert.equal(a.trades[0].exitReason,'손절 · 같은 봉 목표 동시 도달');
 console.log('PASS: explicit target opt-in, unchanged original exits, stop-first ambiguous candle');
}
if(require.main===module){targetTests();if(!process.argv.includes('--quick'))check(JSON.parse(fs.readFileSync('/tmp/paper-long-cache/market.json')));}
