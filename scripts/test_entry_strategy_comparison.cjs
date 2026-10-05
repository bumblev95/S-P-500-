'use strict';
const assert=require('node:assert/strict');
const C=require('./entry_strategy_comparison.cjs'),B=require('./backtest_entry_rules.cjs'),P=require('./entry-study-v1/paper-engine.cjs');
const DAY=86400000;
function rows(n=260){
 const out=[];let t=Date.parse('2020-01-02T14:30:00Z');
 for(let i=0;i<n;i++){
  while([0,6].includes(new Date(t).getUTCDay()))t+=DAY;
  const close=100+i*.12;
  out.push({date:new Date(t).toISOString().slice(0,10),t,end:t+23400000,
   open:close-.1,high:close+.4,low:close-.4,close,volume:1000000});t+=DAY;
 }
 return out;
}
// Wilder's 2-period seed and recurrence have known hand-calculated values.
const rsiRows=[10,11,10,12,11].map((close,i)=>({date:String(i),close,high:close+.1,low:close-.1}));
const values=C.features(rsiRows);
assert.equal(values[2].rsi2,50);
assert.ok(Math.abs(values[3].rsi2-100*2.5/3)<1e-12);
assert.ok(Math.abs(values[4].rsi2-50)<1e-12);
assert.equal(C.features(rsiRows.map(r=>({...r,close:10,high:10.1,low:9.9})))[4].rsi2,50);

const bars=rows(),calendar=new Map(bars.map((r,i)=>[r.date,i]));
const baseline=C.features(bars,calendar),edited=structuredClone(bars);
for(let i=231;i<edited.length;i++)for(const k of ['open','high','low','close'])edited[i][k]*=2;
assert.deepEqual(C.features(edited,calendar).slice(0,231),baseline.slice(0,231),'Features must be prefix invariant');
const highEdited=structuredClone(bars);highEdited[230].high=10000;
assert.equal(C.features(highEdited,calendar)[230].priorHigh55,baseline[230].priorHigh55,'Channel excludes current bar');
const missing=structuredClone(bars);missing.splice(210,1);
assert.equal(C.features(missing,calendar)[220].consecutive,11,'A missing session resets entry warmup');

const f={...baseline[230],close:135,open:134.9,atr:1,ma5:134,ma20:132,ma50:125,ma200:115,
 priorHigh55:134,momentum:.1,consecutive:231},market={...f,close:135,ma200:120};
assert.ok(C.signal(f,market,'channel55'));
assert.equal(C.signal(f,{...market,close:119},'channel55'),null,'Actual historical SPY price gate');
assert.equal(C.signal({...f,atr:6},market,'channel55'),null,'8% stop-distance limit');
assert.equal(C.signal({...f,consecutive:199},market,'channel55'),null);
assert.ok(C.signal({...f,previousLow:131.9,previousMA20:132,previousClose:134},market,'pullback20'));
assert.ok(C.signal({...f,close:130,ma5:132,rsi2:5},market,'rsi2'));
assert.equal(C.signal({...f,close:130,ma5:132,rsi2:10},market,'rsi2'),null);
assert.throws(()=>C.signal(f,market,'optimized'),/Unknown fixed method/);

// Complete portfolio prefix cannot change when only future prices change.
const data={cutoff:bars.at(-1).date,stocks:{SPY:{sector:'ETF',rows:bars},AAA:{sector:'A',rows:bars}}};
data.stocks.AAA=structuredClone(data.stocks.AAA);
data.stocks.AAA.rows[230]={...data.stocks.AAA.rows[230],close:132,open:131.9,high:132.2,low:130.6};
for(let i=231;i<bars.length;i++)for(const k of ['open','high','low','close'])data.stocks.AAA.rows[i][k]+=4.4;
const future=structuredClone(data);
for(let i=235;i<bars.length;i++)for(const k of ['open','high','low','close'])future.stocks.AAA.rows[i][k]*=3;
const run=C.run(data,{start:bars[225].date}),rerun=C.run(future,{start:bars[225].date});
for(const id of Object.keys(run.details)){
 assert.deepEqual(run.details[id].daily.slice(0,10),rerun.details[id].daily.slice(0,10));
 assert.deepEqual(run.details[id].account.curve.slice(0,11),rerun.details[id].account.curve.slice(0,11));
 assert.equal(run.details[id].account.curve[1].exposure,0,'No same-day signal fill');
 for(const p of [...run.details[id].account.trades,...run.details[id].account.positions]){
  assert.ok(p.entryAt>p.signalAt);assert.ok(Number.isInteger(p.qty));
 }
}
assert.ok(run.details.channel55.account.events.some(e=>e.type==='entry'),'Causal account fixture must actually enter');

// Shared engine conventions: entry-bar stop priority, gaps, integer shares.
const bar={...bars[231],open:100,high:110,low:90,close:101};
const order={id:'fixture',symbol:'AAA',sector:'A',side:'long',pattern:'pullback20',at:bar.t-DAY,
 createdAt:bar.t-DAY,notBefore:bar.t-1,expires:bar.end+DAY,price:100,stop:95,target:109,atr:4,rank:100,holdBars:84};
const a=B.newAccount(bar);a.pending=[order];C.execute(a,{AAA:bar,SPY:bar},bar,C.cfgFor(false));
assert.equal(a.trades[0].exitReason,'stop before same-bar target');
assert.equal(a.trades[0].exit,95*(1-P.CONFIG.stocks.slip));
assert.ok(Number.isInteger(a.trades[0].qty));
const gap=B.newAccount(bar);gap.pending=[{...order,price:90}];C.execute(gap,{AAA:bar,SPY:bar},bar,C.cfgFor(false));
assert.equal(gap.positions.length,0);assert.equal(Object.values(gap.rejections).reduce((s,n)=>s+n,0),1);

// Do not finance an opening entry with a sale that happens later that bar.
const capacity=B.newAccount(bar);capacity.pending=['A','B','C','D','E','F'].map((symbol,i)=>({...order,
 id:symbol,symbol,sector:symbol,pattern:'channel55',target:null,stop:98,atr:1,rank:6-i}));
const live={...bar,high:100.3,low:99,close:100};
const all=Object.fromEntries(['A','B','C','D','E','F'].map(s=>[s,live]));
C.execute(capacity,all,live,C.cfgFor(false));assert.equal(capacity.positions.length,5);
C.queue(capacity,[{...order,id:'G',symbol:'G',sector:'G',at:live.end,pattern:'channel55',target:null,stop:98,atr:1}]);
const second={...live,t:live.t+DAY,end:live.end+DAY,date:new Date(live.t+DAY).toISOString().slice(0,10),low:90};
C.execute(capacity,{...Object.fromEntries(['A','B','C','D','E','G'].map(s=>[s,second]))},second,C.cfgFor(false));
assert.equal(capacity.events.filter(e=>e.type==='entry').length,5,'Five later-bar exits cannot fund sixth opening entry');

// Closing-price exits and revised channel stops first apply at next open.
const exit=B.newAccount(live);exit.id='exit';exit.method='channel55';exit.pending=[{...order,pattern:'channel55',target:null,stop:95}];
C.execute(exit,{AAA:live},live,C.cfgFor(false));assert.equal(exit.positions.length,1);
const closing={...f,end:live.end,close:101,priorLow20:99,ma200:90};
C.observe(exit,{AAA:closing},{...closing,close:101,ma200:90},[]);
assert.equal(exit.positions[0].stop,95);assert.equal(exit.positions[0].pendingStop.price,99);
const third={...second,open:100,low:98,high:101,close:100};
C.execute(exit,{AAA:third},third,C.cfgFor(false));assert.equal(exit.trades[0].exit,99*(1-P.CONFIG.stocks.slip));
const timeout=C.heldControl({...closing,close:100,ma5:101},{...closing,close:101,ma200:90},'rsi2',{bars:10,holdBars:10,stop:95});
assert.equal(timeout.reason,'holding limit at next open');
const regime=B.newAccount(live);regime.id='regime';regime.method='channel55';regime.pending=[{...order,pattern:'channel55',target:null,stop:95}];
C.execute(regime,{AAA:live},live,C.cfgFor(false));
C.observe(regime,{AAA:closing},{...closing,close:90,ma200:100},[]);
assert.equal(regime.positions.length,1,'Closing market regime cannot retroactively exit');
C.execute(regime,{AAA:{...third,low:100,close:100}},third,C.cfgFor(false));
assert.equal(regime.trades[0].exitReason,'SPY below SMA200');assert.equal(regime.trades[0].exitAt,third.t);

// Training diagnostic excludes forward labels ending in the later block.
const labels={20:[{date:'2022-12-01',endDate:'2023-01-03',net:9,benchmark:0,excess:9},
 {date:'2022-11-01',endDate:'2022-12-01',net:.1,benchmark:.02,excess:.08}]};
const early=C.summarizeLabels(labels,C.PERIODS.early)[20];
assert.equal(early.observations,1);assert.equal(early.excluded.crossesPeriodEnd,1);assert.equal(early.meanNet,.1);
assert.deepEqual(C.parseCSV(C.csv([{name:'한글, "quote"',v:'a\nb'}],['name','v'])),[{name:'한글, "quote"',v:'a\nb'}]);
assert.deepEqual(['BRK-B','BR','BF-B','BF-A'].map(symbol=>({symbol,rank:1})).sort(C.compare).map(q=>q.symbol),
 ['BRK-B','BR','BF-B','BF-A'].sort((a,b)=>a.localeCompare(b)));
console.log('Strategy comparison: Wilder seed, causal features/accounts, next-open exits/stops, funding order and split labels passed');
