const assert=require('node:assert/strict'),fs=require('node:fs');
const T=require('../assets/technical-guide.js'),A=require('../assets/stock-assessment.js');
const day='2026-10-02',now=Date.parse(day+'T23:00:00Z');
const market={generatedAt:day+'T22:00:00Z',credit:{status:'stable'},indicators:
  ['NFCI','STLFSI4','DRTSCILM','FUNDING'].map(id=>({id,status:'ready',asOf:day,maxAgeDays:5}))};
function fixture(mode='breakout'){
  const history=Array.from({length:260},(_,j)=>({date:new Date(Date.parse(day)-(259-j)*86400000).toISOString().slice(0,10),
    close:mode==='pullback'?(j===259?104:j>=239&&j<=243?110:j>=244?102:90+j*.05):
      j===259?100:90+j*.036+Math.sin(j*.3)*.25,volume:1000}));
  return {symbol:'TEST',status:'ready',fresh:true,asOf:day,price:history.at(-1).close,history,
    inputs:{ma20:99,ma50:95,ma200:90,return1m:.04,return3m:.12,volatility4m:.2}};
}
const assess=e=>A.evaluate(e,market,null,126,now),breakEntry=fixture(),a=assess(breakEntry),p=a.plan;
assert.equal(p.code,'buy');assert.equal(p.strategy,'breakout');assert.equal(p.target1,null);
assert.equal(p.rr,null,'A trend-following breakout must not manufacture a profit target');
assert(p.indicators.rsi>75,'Control specifically covers RSI overbought in a strong trend');
assert(!p.blocks.length);assert.equal(p.range.basis,'close-volatility');
assert.equal(p.breakoutLevel,Math.max(...breakEntry.history.slice(-56,-1).map(q=>q.close)));
assert(p.setups[1].state==='ready');assert.equal(p.holding.code,'hold');
assert(!A.signals(breakEntry,a,market,now).negative.some(q=>q.id==='resistance-missing'));

// Missing/weak volume is visible, but cannot silently replace the original
// price breakout rule with a volume-only veto. No volume value is invented.
for(const volume of [10,1500,null]){
  const e=structuredClone(breakEntry);e.history.at(-1).volume=volume;
  const q=assess(e);assert.equal(q.plan.code,'buy');
  assert.equal(q.plan.indicators.relativeVolume,volume===null?null:volume/1000);
  assert.equal(q.plan.setups[1].state,'ready');
}
assert.match(p.reason,/거래량 보강 없음/);

// Actual pullback confirmation can enter even without a new high. Being in
// the zone alone is insufficient, and the structural target is not inflated.
const pull=fixture('pullback'),pullA=assess(pull);
assert.equal(pullA.plan.code,'buy');assert.equal(pullA.plan.strategy,'pullback');
assert.equal(pullA.plan.target1,110);assert(pullA.plan.rr>=1.5);
assert(pull.price<=pullA.plan.breakoutLevel);assert.equal(pullA.plan.setups[0].state,'ready');
const flatBounce=structuredClone(pull);flatBounce.history.at(-2).close=pull.price;
assert.notEqual(assess(flatBounce).plan.code,'buy','An unchanged close is not rebound confirmation');

// A broken support is retained from prior observations, not replaced with a
// lower support below today. Holding responses are independent from entry.
const broken=structuredClone(pull);broken.price=101;broken.history.at(-1).close=101;
broken.inputs={...broken.inputs,ma20:104,ma50:100,ma200:95};
const brokenA=assess(broken);
assert.equal(brokenA.plan.exitLevel,102);assert.equal(brokenA.plan.code,'confirm');
assert.equal(brokenA.decision,'지지 회복 대기');
const bearish=structuredClone(breakEntry);
bearish.history=bearish.history.map((q,j)=>({...q,close:120-20*j/259}));
bearish.inputs={...bearish.inputs,ma20:110,ma50:115,ma200:120,return1m:-.07,return3m:-.15};
const bearishA=assess(bearish);
assert.equal(bearishA.plan.code,'avoid');assert.equal(bearishA.plan.holding.code,'reduce');

// Price extension and stop risk are explicit, strategy-specific blockers.
const chase=structuredClone(breakEntry);chase.price=105;chase.history.at(-1).close=105;
const chaseA=assess(chase);assert.equal(chaseA.plan.code,'overextended');
assert.equal(chaseA.plan.breakoutLevel,p.breakoutLevel);
const wide=structuredClone(breakEntry);wide.inputs.volatility4m=.9;
const wideA=assess(wide);assert.notEqual(wideA.plan.code,'buy');assert.match(wideA.reason,/위험 폭/);
const caution=structuredClone(breakEntry);caution.inputs.volatility4m=.45;
assert.equal(assess(caution).plan.code,'buy');
const cautiousMarket={...market,credit:{status:'watch'}};
assert.notEqual(A.evaluate(caution,cautiousMarket,null,126,now).plan.code,'buy');

// Market and data failures block entry. Market failure does not manufacture
// a sell instruction for someone holding a stock whose price trend is intact.
for(const m of [null,{...market,credit:{status:'risk'}}]){
  const q=A.evaluate(breakEntry,m,null,126,now);assert.notEqual(q.plan.code,'buy');
  assert.equal(q.plan.holding.code,'hold');
  assert(q.plan.setups.every(s=>s.state!=='ready'));
}
for(const e of [{...breakEntry,fresh:false},{...breakEntry,price:99},
  {...breakEntry,history:breakEntry.history.slice(-30)}]){
  const q=assess(e);assert.equal(q.plan.code,'unavailable');assert.equal(q.plan.holding.code,'unavailable');
  assert(!/NaN|Infinity|undefined/.test(A.panel(q)));
}
assert.equal(assess({...breakEntry,status:'missing',predictions:{}}).plan.code,'buy',
  'Missing forecast output must not hide valid observed-price entry conditions');

// No leakage from future observations, duplicates or malformed calendar days.
const future=structuredClone(breakEntry);
future.history.push({date:'2026-10-03',close:99999,volume:99999},
  {date:'2026-09-31',close:99999},{date:'2026-08-99',close:99999});
assert.deepEqual(assess(future).plan,p);
const duplicate=structuredClone(breakEntry);duplicate.history.unshift({...duplicate.history[0]});
assert.deepEqual(assess(duplicate).plan,p);

// Complete OHLC enables true-range estimation. The close-only rule must not
// treat an intraday high as broken when the supplied close has not exceeded it.
const bars=structuredClone(breakEntry);
bars.history=bars.history.map(q=>({...q,high:q.close+1,low:q.close-1,open:q.close}));
const barsA=assess(bars);assert.equal(barsA.plan.range.basis,'atr20');
assert.equal(barsA.plan.range.value,2);assert.notEqual(barsA.plan.code,'buy');
assert.equal(barsA.plan.levelBasis,'일별 고가·저가');
const incomplete=structuredClone(bars);delete incomplete.history.at(-3).high;
assert.equal(assess(incomplete).plan.range.basis,'close-volatility');
assert.equal(assess(incomplete).plan.levelBasis,'종가','No hybrid high/close breakout level');

// All quantities scale with price. No hidden dollar-specific threshold.
const scaled=structuredClone(breakEntry);scaled.price*=10;
scaled.history=scaled.history.map(q=>({...q,close:q.close*10}));
for(const key of ['ma20','ma50','ma200'])scaled.inputs[key]*=10;
const scaledA=assess(scaled);assert.equal(scaledA.decision,a.decision);
assert(Math.abs(scaledA.plan.riskPct-p.riskPct)<1e-12);
assert(Math.abs(scaledA.plan.breakoutLevel-p.breakoutLevel*10)<1e-9);

const data=JSON.parse(fs.readFileSync('forecasts/latest.json')),actualMarket=JSON.parse(fs.readFileSync('market/latest.json'));
const all=A.all(data,actualMarket,null,126,Date.parse(actualMarket.generatedAt)),counts={};
for(const x of Object.values(all)){
  counts[x.decision]=(counts[x.decision]||0)+1;
  if(x.plan.code==='buy'){
    assert(!x.plan.blocks.length);assert(x.plan.upstream&&!x.plan.extended);
    assert(x.plan.setups.some(s=>s.key===x.plan.strategy&&s.state==='ready'));
    if(x.plan.strategy==='breakout')assert.equal(x.plan.rr,null);
  }
}
console.log('Entry indicator: independent breakout/pullback, optional volume, high RSI, retained support, holding, market/data gates, causal levels, OHLC fallback and price scaling passed.');
console.log('Snapshot distribution (not performance validation):',counts);
