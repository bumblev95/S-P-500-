'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const S=require('./entry_study.cjs'),B=require('./build_entry_study.cjs'),P=require('./entry-study-v1/paper-engine.cjs');
const T=require('./entry-study-v1/technical-guide.cjs');
const DAY=86400000,base=Date.UTC(2026,0,1),copy=structuredClone;
function fixture(mode='breakout',ohlc=true){
 const bars=Array.from({length:260},(_,j)=>{
  const close=mode==='pullback'?(j===259?104:j>=239&&j<=243?110:j>=244?102:90+j*.05):90+j*.03+Math.sin(j*.8)*1.2;
  const t=base+j*DAY+14*3600000+30*60000,spread=mode==='pullback'?.4:.6;
  return {t,end:t+23400000-1,date:new Date(t).toISOString().slice(0,10),close,volume:1000,
   ...(ohlc?{open:close,high:close+spread,low:close-spread}:{})};
 });
 if(mode==='breakout'){
  const last=bars.at(-1);last.close=Math.max(...bars.slice(-56,-1).map(r=>ohlc?r.high:r.close))+.1;
  if(ohlc)Object.assign(last,{open:last.close,high:last.close+.6,low:last.close-.6});
 }
 return bars;
}
const feed=(bars,extras={})=>({generatedAt:new Date(bars.at(-1).end+3600000).toISOString(),stocks:{
 TEST:{rows:copy(bars),sector:'test'},SPY:{rows:copy(bars),sector:'market'},...extras}});
function credit(now,status='stable'){
 const day=new Date(now).toISOString().slice(0,10);
 return {generatedAt:new Date(now).toISOString(),credit:{status},indicators:
  ['NFCI','STLFSI4','DRTSCILM','FUNDING'].map(id=>({id,status:'ready',asOf:day,maxAgeDays:5}))};
}
function setup(mode='breakout',ohlc=true){
 const bars=fixture(mode,ohlc),initial=feed(bars.slice(0,-1)),start=bars.at(-2).end+3600000;
 const m=S.manifest(initial,start),a=S.create(m,initial,null);a.qualityKey=S.hash([]);
 return {bars,start,m,a,now:bars.at(-1).end+3600000};
}
function nextBar(bars,values={}){
 const prev=bars.at(-1),t=prev.t+DAY,px=prev.close;
 return {t,end:t+23400000-1,date:new Date(t).toISOString().slice(0,10),open:px,close:px,high:px+.3,low:px-.3,volume:1000,...values};
}
let checks=0;function test(name,fn){fn();checks++;console.log('PASS '+name);}

test('genesis is cash-only; latest warmup is never traded; universe/costs are frozen',()=>{
 const x=setup();
 for(const a of Object.values(x.a.accounts)){assert.equal(a.cash,10000);assert.equal(a.events.length,0);assert.equal(a.positions.length,0);assert.equal(a.pending.length,0);}
 assert.deepEqual(x.m.costRisk,{risk:.01,maxPositions:5,maxWeight:.2,fee:.0005,slip:.0005,step:DAY,warmup:205});
 assert.deepEqual(x.m.universe,[{symbol:'TEST',sector:'test'}]);assert.equal(x.m.safety.autoPromotion,false);
 const unchanged=S.advance(x.a,x.m,feed(x.bars.slice(0,-1)),credit(x.start),null,x.start+1000);
 assert.equal(unchanged.changed,false);assert.equal(unchanged.state.accounts.indicator.events.length,0);
});
test('mid-session initialization can observe the later close but never fill the earlier open',()=>{
 const bars=fixture(),start=bars.at(-1).t+3600000,market=feed(bars);
 const m=S.manifest(market,start),state=S.create(m,market,null);state.qualityKey=S.hash([]);
 assert.equal(state.history.TEST.at(-1).date,bars.at(-2).date);
 const now=bars.at(-1).end+3600000,result=S.advance(state,m,market,credit(now),null,now).state;
 for(const a of Object.values(result.accounts)){
  assert.equal(a.positions.length,0);assert.equal(a.trades.length,0);assert.equal(a.curve.length,2);
 }
 assert.equal(result.accounts.indicator.pending.length,1);assert(result.accounts.indicator.pending[0].notBefore>bars.at(-1).end);
});
test('PR #19 rule parity, actual 55-bar highs and close-only fallback; both setups enter',()=>{
 for(const mode of ['breakout','pullback'])for(const hl of [true,false]){
  const x=setup(mode,hl),e=S.entry(x.bars,'TEST',x.now),plan=S.assess(x.bars,'TEST',credit(x.now),x.now).plan;
  assert.deepEqual(plan,T.plan(e,null,credit(x.now),x.now));assert.equal(plan.code,'buy');assert.equal(plan.strategy,mode);
  const advanced=S.advance(x.a,x.m,feed(x.bars),credit(x.now),null,x.now),a=advanced.state.accounts.indicator;
  assert.equal(a.pending.length,1);assert.equal(a.positions.length,0);assert.equal(a.trades.length,0);
  const q=a.events.find(e=>e.type==='signal');assert.equal(q.levelBasis,hl?'일별 고가·저가':'종가');
  assert.equal(q.levelBasisCode,hl?'ohlc-high-low':'close-only-fallback');
  assert.equal(q.rangeBasis,hl?'atr20':'close-volatility');
  if(mode==='breakout')assert.equal(a.pending[0].target,null);else assert(a.pending[0].target>q.price);
  const rerun=S.advance(advanced.state,x.m,feed(x.bars),credit(x.now),null,x.now+1000);
  assert.equal(rerun.changed,false);assert.deepEqual(rerun.state,advanced.state);
 }
 const x=setup(),e=S.entry(x.bars,'TEST',x.now);e.history.at(-40).high=110;
 assert.equal(T.plan(e,null,credit(x.now),x.now).breakoutLevel,110);
 assert.notEqual(T.plan(e,null,credit(x.now),x.now).code,'buy','20-bar breakout is not a 55-bar breakout');
});
test('optional volume and AI cannot change the frozen observed-price rule',()=>{
 const x=setup();
 for(const volume of [null,10,1500]){
  const bars=copy(x.bars);for(const bar of bars)delete bar.volume;
  if(volume!==null)bars.at(-1).volume=volume;
  assert.equal(S.assess(bars,'TEST',credit(x.now),x.now).plan.code,'buy');
 }
 const e=S.entry(x.bars,'TEST',x.now);e.predictions={126:{base:1e9}};
 assert.deepEqual(T.plan(e,e.predictions,credit(x.now),x.now),T.plan(e,null,credit(x.now),x.now));
});
test('new symbols are excluded; stale/unknown/risk credit blocks new entries only',()=>{
 const x=setup(),extra={EXTRA:{rows:copy(x.bars),sector:'other'}};
 const n=S.advance(x.a,x.m,feed(x.bars,extra),credit(x.now),null,x.now);
 assert.deepEqual(Object.keys(n.state.history).sort(),['SPY','TEST']);assert.equal(n.state.accounts.indicator.signals.length,1);
 for(const status of ['unknown','risk']){
  const z=S.advance(x.a,x.m,feed(x.bars),credit(x.now,status),null,x.now);
  assert.equal(z.state.accounts.indicator.pending.length,0);
  assert.equal(z.state.accounts.indicator.signals[0].holding.code,'hold');
 }
 const stale=credit(x.start-10*DAY);
 assert.equal(S.advance(x.a,x.m,feed(x.bars),stale,null,x.now).state.accounts.indicator.pending.length,0);
});
test('next-open fills, whole-share sizing, same costs and no opening before observation',()=>{
 const x=setup(),signal=S.advance(x.a,x.m,feed(x.bars),credit(x.now),null,x.now).state;
 const bar=nextBar(x.bars),all=[...x.bars,bar],now=bar.end+3600000;
 const out=S.advance(signal,x.m,feed(all),credit(now),null,now).state.accounts.indicator;
 assert.equal(out.positions.length,1);const p=out.positions[0];
 assert.equal(p.entryAt,bar.t);assert(p.entryAt>p.orderCreatedAt);assert.equal(p.entry,bar.open*1.0005);
 assert.equal(p.entryFee,p.qty*p.entry*.0005);assert.equal(p.qty,Math.floor(p.qty));assert(p.margin<=2000);
 assert.equal(p.levelBasis,'일별 고가·저가');assert.equal(p.target,null);
 const clone=copy(out);P.close(clone,clone.positions[0],clone.positions[0].stop,bar.end,'test stop',x.m.costRisk,now);
 assert(10000-clone.cash<=100,'risk sizing includes both fees and stop slippage');
 const late=x.bars.at(-1).t+DAY+2*3600000; // current next session already opened
 const observedLate=S.advance(x.a,x.m,feed(x.bars),credit(late),null,late).state;
 const skipped=S.advance(observedLate,x.m,feed(all),credit(now),null,now).state.accounts.indicator;
 assert.equal(skipped.positions.length,0);assert.equal(skipped.trades.length,0);assert.equal(skipped.pending[0].notBefore,late);
});
test('stock position/sector/cash limits apply identically to targetless entries',()=>{
 const x=setup(),sectors={A:'tech',B:'tech',C:'tech',D:'finance',E:'finance',F:'energy',G:'utility'};
 const market=(bars)=>({generatedAt:new Date(bars.at(-1).end+3600000).toISOString(),stocks:{SPY:{rows:copy(bars),sector:'market'},
  ...Object.fromEntries(Object.entries(sectors).map(([symbol,sector])=>[symbol,{rows:copy(bars),sector}]))}});
 const initial=market(x.bars.slice(0,-1)),m=S.manifest(initial,x.start),state=S.create(m,initial,null);state.qualityKey=S.hash([]);
 const signal=S.advance(state,m,market(x.bars),credit(x.now),null,x.now).state;
 assert.equal(signal.accounts.indicator.pending.length,7);
 const next=nextBar(x.bars),now=next.end+3600000,out=S.advance(signal,m,market([...x.bars,next]),credit(now),null,now).state.accounts.indicator;
 assert.equal(out.positions.length,5);assert.equal(out.positions.filter(p=>p.sector==='tech').length,2);
 assert.equal(out.positions.filter(p=>p.sector==='finance').length,2);assert(out.cash>=0);
 assert(out.events.some(e=>e.type==='cancel'&&e.reason.includes('업종')));assert(out.events.some(e=>e.type==='cancel'&&e.reason==='포지션 한도'));
});
test('close-only signal never fabricates an OHLC execution; missing/revised sources cancel',()=>{
 const x=setup('breakout',false),signal=S.advance(x.a,x.m,feed(x.bars),credit(x.now),null,x.now).state;
 const bar=nextBar(x.bars);delete bar.open;delete bar.high;delete bar.low;
 const now=bar.end+3600000,out=S.advance(signal,x.m,feed([...x.bars,bar]),credit(now),null,now).state;
 assert.equal(out.accounts.indicator.positions.length,0);assert.equal(out.accounts.indicator.trades.length,0);
 assert(out.accounts.indicator.events.some(e=>e.type==='cancel'&&e.reason.includes('OHLC')));
 assert(!out.accounts.control.events.some(e=>e.type==='entry'));assert(Number.isFinite(out.accounts.control.cash));
 const y=setup(),pending=S.advance(y.a,y.m,feed(y.bars),credit(y.now),null,y.now).state;
 const bad=feed(y.bars);bad.stocks.TEST.errors=['timeout'];
 const canceled=S.advance(pending,y.m,bad,credit(y.now),null,y.now+1000).state;
 assert.equal(canceled.accounts.indicator.pending.length,0);assert(canceled.accounts.indicator.events.some(e=>e.type==='cancel'));
 const revised=feed(y.bars);revised.stocks.TEST.rows.at(-3).close*=1.1;
 const blocked=S.advance(y.a,y.m,revised,credit(y.now),null,y.now).state;
 assert.equal(blocked.accounts.indicator.pending.length,0);assert.equal(blocked.history.TEST.at(-3).close,y.a.history.TEST.at(-2).close);
});
test('adverse gaps cancel entry; target/stop dual hit stops first; gap stop uses open',()=>{
 const x=setup('pullback'),signal=S.advance(x.a,x.m,feed(x.bars),credit(x.now),null,x.now).state;
 const p=signal.accounts.indicator.pending[0],bar=nextBar(x.bars,{high:p.target+2,low:p.stop-1}),now=bar.end+3600000;
 const closed=S.advance(signal,x.m,feed([...x.bars,bar]),credit(now),null,now).state.accounts.indicator;
 assert.equal(closed.trades.length,1);assert(closed.trades[0].exitReason.includes('동시'));assert(closed.trades[0].net<0);
 const gap=nextBar(x.bars,{open:p.price+10,high:p.price+11,low:p.price+9,close:p.price+10});
 const canceled=S.advance(signal,x.m,feed([...x.bars,gap]),credit(now),null,now).state.accounts.indicator;
 assert.equal(canceled.positions.length,0);assert(canceled.events.some(e=>e.type==='cancel'&&e.reason.includes('이탈')));
 const y=setup(),b=nextBar(y.bars),n=b.end+3600000;
 const holding=S.advance(S.advance(y.a,y.m,feed(y.bars),credit(y.now),null,y.now).state,y.m,feed([...y.bars,b]),credit(n),null,n).state;
 const stop=holding.accounts.indicator.positions[0].stop,down=nextBar([...y.bars,b],{open:stop-5,high:stop-4,low:stop-6,close:stop-5});
 const q=S.advance(holding,y.m,feed([...y.bars,b,down]),credit(down.end+3600000),null,down.end+3600000).state.accounts.indicator;
 assert(q.trades[0].exit<down.open);assert(q.trades[0].exitReason.includes('시가 갭'));
});
test('holding signals and raised stops take effect only after the observed close',()=>{
 const x=setup(),a=x.a.accounts.indicator,entry=x.bars.at(-2).close;
 a.positions=[{id:'held',symbol:'TEST',sector:'test',side:'long',pattern:'breakout',entryAt:x.start,entry,qty:1,margin:entry,
  stop:50,target:null,entryFee:0,funding:0,bars:0,holdBars:Number.MAX_SAFE_INTEGER,levelBasis:'일별 고가·저가'}];a.cash-=entry;
 const bars=copy(x.bars);bars.at(-1).low=60; // a new stop would be hit in this same bar
 const result=S.advance(x.a,x.m,feed(bars),credit(x.now),null,x.now).state,held=result.accounts.indicator.positions[0];
 assert(held.pendingStop);assert.equal(held.stop,50);assert.equal(result.accounts.indicator.trades.length,0);
 assert.equal(held.pendingStop.notBefore,x.now);
 const next=nextBar(bars,{open:held.pendingStop.price+1,high:held.pendingStop.price+2,low:held.pendingStop.price-1,close:held.pendingStop.price+.5});
 const closed=S.advance(result,x.m,feed([...bars,next]),credit(next.end+3600000),null,next.end+3600000).state.accounts.indicator;
 assert.equal(closed.trades.length,1);assert(closed.events.some(e=>e.type==='stopApplied'&&e.executionAt===next.t));
 const low=copy(x.bars);Object.assign(low.at(-1),{open:81,high:82,low:79,close:80});
 const reduce=S.advance(x.a,x.m,feed(low),credit(x.now,'risk'),null,x.now).state.accounts.indicator;
 assert.equal(reduce.positions.length,1);assert.equal(reduce.positions[0].exitNotBefore,x.now);
 assert(reduce.events.some(e=>e.type==='holding'&&e.holding.code==='reduce'),'price-based holding response remains independent of credit');
});
test('catch-up settles posted orders but never creates historical signals; future bars excluded',()=>{
 const x=setup(),b1=nextBar(x.bars),b2=nextBar([...x.bars,b1]),b3=nextBar([...x.bars,b1,b2]);
 const now=b2.end+3600000,out=S.advance(x.a,x.m,feed([...x.bars,b1,b2,b3]),credit(now),null,now);
 assert.equal(out.state.accounts.indicator.positions.length,0);assert.equal(out.state.accounts.indicator.trades.length,0);
 assert(out.state.accounts.indicator.events.filter(e=>e.type==='assessment').every(e=>e.signalAt===b2.end));
 assert.equal(out.state.history.TEST.at(-1).t,b2.t);assert.equal(out.state.observedSessions,1);
 assert.equal(out.state.missedObservationSessions,2);assert.equal(S.comparison(out.state).executionComparable,false);
 const posted=S.advance(x.a,x.m,feed(x.bars),credit(x.now),null,x.now).state;
 const expired=S.advance(posted,x.m,feed(x.bars),credit(x.now+6*DAY),null,x.now+6*DAY).state;
 assert.equal(expired.accounts.indicator.pending.length,0);assert(expired.accounts.indicator.events.some(e=>e.type==='cancel'&&e.reason.includes('만료')));
});
test('same-start control uses frozen legacy engine and comparisons include common costs/exposure',()=>{
 const x=setup(),legacy=copy(x.a.accounts.control),prior=JSON.stringify(legacy);
 const out=S.advance(x.a,x.m,feed(x.bars),credit(x.now),legacy,x.now).state;
 assert.equal(JSON.stringify(legacy),prior,'existing account is read-only');
 const expected=P.run(x.a.accounts.control,feed(x.bars),{mode:'forward',now:x.now});
 assert.deepEqual(out.accounts.control.pending,expected.pending);assert.deepEqual(out.accounts.control.trades,expected.trades);
 const c=S.comparison(out);assert.equal(c.observedSessions,1);assert.equal(c.performanceValidated,false);
 for(const k of ['indicator','control']){
  assert.equal(c[k].assessedStockSessions,1);assert.equal(c[k].return,0);assert.equal(c[k].sessionAverageExposure,0);
  assert(Number.isFinite(c[k].signalsPer100StockSessions));
 }
});
test('append-only persistence, immutable prefix, manifest/chain tampering, truncation and cache recovery',()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'entry-study-'));
 try{
  fs.mkdirSync(path.join(folder,'ledger'));fs.writeFileSync(path.join(folder,'state.json'),'original stock account');
  fs.writeFileSync(path.join(folder,'ledger','old.json'),'original ledger');
  const x=setup(),opts={credit:credit(x.start),existing:null},initial=feed(x.bars.slice(0,-1));
  const first=B.build(initial,x.start,folder,opts),dir=path.join(folder,'entry-study',S.VERSION);
  const file0=path.join(dir,'ledger',fs.readdirSync(path.join(dir,'ledger'))[0]),bytes0=fs.readFileSync(file0,'utf8');
  const second=B.build(feed(x.bars),x.now,folder,{credit:credit(x.now),existing:null});
  assert.equal(second.sequence,1);assert.equal(fs.readFileSync(file0,'utf8'),bytes0);
  const loaded=B.load(dir);assert.equal(loaded.state.accounts.indicator.pending.length,1);assert.equal(loaded.files.length,2);
  B.build(feed(x.bars),x.now+1000,folder,{credit:credit(x.now),existing:null});assert.equal(B.load(dir).files.length,2);
  assert.equal(fs.readFileSync(path.join(folder,'state.json'),'utf8'),'original stock account');
  assert.equal(fs.readFileSync(path.join(folder,'ledger','old.json'),'utf8'),'original ledger');
  const manifestPath=path.join(dir,'manifest.json'),original=fs.readFileSync(manifestPath,'utf8'),m=JSON.parse(original);
  m.universe[0].symbol='CHANGED';fs.writeFileSync(manifestPath,JSON.stringify(m));assert.throws(()=>B.load(dir),/chain invalid/);fs.writeFileSync(manifestPath,original);
  const tampered=JSON.parse(bytes0);tampered.state.accounts.indicator.cash=99999;fs.writeFileSync(file0,JSON.stringify(tampered));assert.throws(()=>B.load(dir),/chain invalid/);fs.writeFileSync(file0,bytes0);
  const tailPath=path.join(dir,'ledger',loaded.files.at(-1)),tail=fs.readFileSync(tailPath,'utf8');
  fs.unlinkSync(tailPath);assert.throws(()=>B.load(dir),/truncated/);fs.writeFileSync(tailPath,tail);
  fs.writeFileSync(path.join(dir,'latest.json'),JSON.stringify(first));assert.equal(B.load(dir).state.accounts.indicator.pending.length,1);
  const repaired=B.build(feed(x.bars),x.now+1000,folder,{credit:credit(x.now),existing:null});assert.equal(repaired.ledgerHash,second.ledgerHash);
  assert.equal(fs.readFileSync(file0,'utf8'),bytes0);
  const filledBar=nextBar(x.bars),filledNow=filledBar.end+3600000;
  B.build(feed([...x.bars,filledBar]),filledNow,folder,{credit:credit(filledNow),existing:null});
  const position=B.load(dir).state.accounts.indicator.positions[0];assert(position);
  const stopBar=nextBar([...x.bars,filledBar],{open:position.stop-2,high:position.stop-1,low:position.stop-3,close:position.stop-2});
  const closedNow=stopBar.end+3600000;
  const report=B.build(feed([...x.bars,filledBar,stopBar]),closedNow,folder,{credit:credit(closedNow),existing:null});
  const reconstructed=B.load(dir).state.accounts.indicator;
  assert.equal(reconstructed.trades.length,1);assert.equal(report.comparison.indicator.realized,reconstructed.trades[0].net);
  const closedPrefix=JSON.stringify(reconstructed.trades);
  B.build(feed([...x.bars,filledBar,stopBar]),closedNow+1000,folder,{credit:credit(closedNow),existing:null});
  assert.equal(JSON.stringify(B.load(dir).state.accounts.indicator.trades),closedPrefix);
 }finally{fs.rmSync(folder,{recursive:true,force:true});}
});
test('read-only existing comparisons detect cost drift and preserve opening holdings',()=>{
 const x=setup(),existing=P.create('stocks',x.start);
 existing.positions=[{id:'legacy',symbol:'TEST',side:'long',qty:1,margin:100,entry:100,entryFee:0,funding:0,pattern:'portfolioTrend'}];
 existing.cash=9900;existing.marks={TEST:100};
 const cfg=copy(x.m.costRisk),state=S.create(x.m,feed(x.bars.slice(0,-1)),existing,cfg);state.qualityKey=S.hash([]);
 const bytes=JSON.stringify(existing);assert.equal(S.comparison(state).existing.startPositions,1);
 assert.equal(S.comparison(state).existing.sameCostRiskAssumptions,true);
 cfg.fee*=2;
 const out=S.advance(state,x.m,feed(x.bars),credit(x.now),existing,x.now,cfg).state;
 assert.equal(S.comparison(out).existing.sameCostRiskAssumptions,false);assert.equal(JSON.stringify(existing),bytes);
 const changed=copy(x.m);changed.costRisk.risk=.02;assert.throws(()=>S.advance(state,changed,feed(x.bars),credit(x.now),existing,x.now),/settings changed/);
});
console.log('Entry study: '+checks+' scenario groups passed. Synthetic execution tests are not profitability evidence.');
