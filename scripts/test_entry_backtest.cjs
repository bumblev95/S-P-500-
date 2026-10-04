'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const B=require('./backtest_entry_rules.cjs'),T=require('./entry-study-v1/technical-guide.cjs'),P=require('./entry-study-v1/paper-engine.cjs');
const DAY=86400000;
if(require('../assets/technical-guide.js').POLICY.version===T.POLICY.version){
 assert.ok(fs.readFileSync(require.resolve('./entry-study-v1/technical-guide.cjs')).equals(fs.readFileSync(require.resolve('../assets/technical-guide.js'))),
  'The same named production/frozen version must match; new rules require a new version');
}
function rows(n=245){
 const out=[];let time=Date.parse('2025-01-02T14:30:00Z');
 for(let i=0;i<n;i++){
  while([0,6].includes(new Date(time).getUTCDay()))time+=DAY;
  const close=100+i*.12;
  out.push({date:new Date(time).toISOString().slice(0,10),t:time,end:time+6.5*3600000,
   open:close-.1,high:close+1.9,low:close-1.9,close,volume:1000000});time+=DAY;
 }
 const r=out[230];r.close+=2;r.high=r.close+.3;r.open=r.close-.1;
 for(let i=231;i<out.length;i++)for(const k of ['open','high','low','close'])out[i][k]+=2;
 return out;
}
const source={sector:'test',rows:rows()},date=source.rows[230].date;
const rounded=structuredClone(source);rounded.rows[230].signalPrice=129.600001;
assert.equal(B.makeEntry(rounded.rows.slice(0,231),'AAA',Date.parse(date+'T23:59:59Z')).price,129.600001);
assert.equal(B.makeEntry(source.rows.slice(0,231),'AAA',Date.parse(date+'T23:59:59Z')).price,129.6);
const stable=B.assessPrefix(source,'AAA',230,'stable');
assert.equal(stable.plan.code,'buy');assert.equal(stable.plan.strategy,'breakout');
assert.equal(B.assessPrefix(source,'AAA',230,'watch').plan.code,'riskwait');

// Signal features and the early account prefix cannot see appended/revised future bars.
const mutated=structuredClone(source);
for(let i=231;i<mutated.rows.length;i++)for(const k of ['open','high','low','close'])mutated.rows[i][k]*=3;
assert.deepEqual(B.assessPrefix(mutated,'AAA',230,'stable'),stable);
const input={cutoff:source.rows.at(-1).date,stocks:{AAA:source,SPY:{sector:'ETF / index',rows:rows()}}};
const result=B.run(input,{start:date,statuses:['stable']});
const revised=structuredClone(input);revised.stocks.AAA=mutated;
const result2=B.run(revised,{start:date,statuses:['stable']});
assert.deepEqual(result.details.stable.daily[0],result2.details.stable.daily[0]);
assert.deepEqual(result.details.stable.account.curve.slice(0,2),result2.details.stable.account.curve.slice(0,2));
assert.equal(result.details.stable.account.curve[1].exposure,0,'No entry on signal day');
const account=result.details.stable.account;
const entries=[...account.trades,...account.positions];
assert.ok(entries.length>0);
for(const p of entries)assert.ok(p.entryAt>p.signalAt,'Next-open fill only');
for(const r of result.details.stable.daily)if(r.buy>0)assert.equal(r.waiting.length,0);

// Risk/unknown/stale market gates apply before a valid price-only setup.
const now=Date.parse(date+'T23:59:59Z');
assert.equal(T.plan(stable.entry,null,B.scenarioFeed('risk',date),now).code,'avoid');
const stale=B.scenarioFeed('stable',date);stale.generatedAt=new Date(now-4*DAY).toISOString();
assert.equal(T.plan(stable.entry,null,stale,now).code,'unavailable');
const missing=B.scenarioFeed('stable',date);missing.indicators=[];
assert.equal(T.plan(stable.entry,null,missing,now).code,'unavailable');
assert.notEqual(T.plan({...stable.entry,fresh:false},null,B.scenarioFeed('stable',date),now).code,'buy');

// Fixed-horizon labels start at the next open and count only mature complete windows.
const indexed=B.indexData(input),label=B.outcome(indexed,'AAA',date,2);
const cost=(1-P.CONFIG.stocks.slip)*(1-P.CONFIG.stocks.fee)/((1+P.CONFIG.stocks.slip)*(1+P.CONFIG.stocks.fee));
assert.equal(label.net,source.rows[232].close/source.rows[231].open*cost-1);
assert.equal(B.outcome(indexed,'AAA',date,63).excluded,'immature');
const withGap=structuredClone(input);withGap.stocks.AAA.rows.splice(231,1);
assert.equal(B.outcome(B.indexData(withGap),'AAA',date,2).excluded,'missingSession');
const bad=structuredClone(input);delete bad.stocks.AAA.rows[231].open;
assert.throws(()=>B.indexData(bad),/Invalid OHLC/);

// Frozen execution keeps same-bar stop priority, gap cancellation and share limits.
const bar={...source.rows[231],open:100,high:110,low:90,close:101};
const fake={SPY:{rows:[bar],byDate:new Map([[bar.date,0]])},AAA:{rows:[bar],byDate:new Map([[bar.date,0]])}};
const a=B.newAccount(bar);
a.pending=[{id:'test',symbol:'AAA',sector:'test',side:'long',pattern:'pullback',at:bar.t-DAY,
 createdAt:bar.t-DAY,notBefore:bar.t-1,expires:bar.end+DAY,price:100,stop:95,target:109,atr:4,rank:100,holdBars:100}];
B.execute(a,fake,bar);
assert.equal(a.trades.length,1);assert.equal(a.trades[0].exitReason,'stop before same-bar target');
assert.equal(a.trades[0].exit,95*(1-P.CONFIG.stocks.slip));
assert.ok(Number.isInteger(a.trades[0].qty));
const gap=B.newAccount(bar);gap.pending=[{...a.trades[0],id:'gap',price:90,atr:4,notBefore:bar.t-1,expires:bar.end+DAY}];
B.execute(gap,fake,bar);assert.equal(gap.positions.length,0);assert.equal(Object.values(gap.rejections).reduce((s,n)=>s+n,0),1);

// Same score ordering agrees with the production ticker comparator.
const A=require('../assets/stock-assessment.js');
const symbols=['BRK-B','BR','BF-B','BF-A','AAA'];
assert.deepEqual(symbols.map(symbol=>({symbol,plan:{ts:100}})).sort(B.compare).map(q=>q.symbol),
 symbols.map(symbol=>({symbol,score:100})).sort(A.compare).map(q=>q.symbol));
// Fixed real examples: raw quote equality must not replace the rounded CSV
// price in a moving-average score boundary or a strict pullback rebound test.
const roundingFixture=JSON.parse(fs.readFileSync(require.resolve('./fixtures/entry-backtest-rounding.json')));
for(const e of Object.values(roundingFixture)){
 const now=Date.parse(e.asOf+'T23:59:59Z'),feed=B.scenarioFeed('stable',e.asOf);
 const bars=e.history.map(r=>({...r,t:Date.parse(r.date+'T14:30:00Z'),end:Date.parse(r.date+'T21:00:00Z')}));
 const expected=T.plan(e,null,feed,now),actual=T.plan(B.makeEntry(bars,e.symbol,now),null,feed,now);
 assert.deepEqual([actual.ts,actual.code],[expected.ts,expected.code],e.symbol+' snapshot rounding parity');
 const raw=T.plan(require('./entry_study.cjs').entry(bars,e.symbol,now),null,feed,now);
 assert.notDeepEqual([raw.ts,raw.code],[expected.ts,expected.code],'Fixture must retain the original boundary');
}
console.log('Entry backtest: causal features, market gates, execution and outcome chronology passed');
