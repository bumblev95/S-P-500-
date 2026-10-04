'use strict';
// Forward observations only. The vendored modules are experiment inputs, not
// shared production logic: changing them requires a new study directory/version.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const T=require('./entry-study-v1/technical-guide.cjs');
const P=require('./entry-study-v1/paper-engine.cjs');
const VERSION='entry-context-v1-forward-v1',DAY=86400000,finite=Number.isFinite;
const copy=x=>JSON.parse(JSON.stringify(x));
function canonical(x){
 if(x===null||typeof x!=='object'){
  if(typeof x==='number'&&!finite(x))throw Error('Non-finite study input');
  return JSON.stringify(x);
 }
 if(Array.isArray(x))return '['+x.map(canonical).join(',')+']';
 return '{'+Object.keys(x).sort().map(k=>JSON.stringify(k)+':'+canonical(x[k])).join(',')+'}';
}
const hash=x=>crypto.createHash('sha256').update(typeof x==='string'?x:canonical(x)).digest('hex');
const CODE=['entry_study.cjs','build_entry_study.cjs','entry-study-v1/technical-guide.cjs','entry-study-v1/paper-engine.cjs',
 'entry-study-v1/simulation-signals.cjs','entry-study-v1/perp-engine.cjs'];
const sourceHashes=()=>Object.fromEntries(CODE.map(p=>[p,hash(fs.readFileSync(path.join(__dirname,p),'utf8'))]));
const validDate=d=>typeof d==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(d)&&finite(Date.parse(d))&&new Date(d).toISOString().slice(0,10)===d;
const validClose=r=>r&&validDate(r.date)&&finite(r.t)&&finite(r.end)&&r.t<r.end&&
 new Date(r.t).toISOString().slice(0,10)===r.date&&finite(r.close)&&r.close>0;
const validOHLC=r=>validClose(r)&&['open','high','low'].every(k=>finite(r[k]))&&
 0<r.low&&r.low<=Math.min(r.open,r.close)&&Math.max(r.open,r.close)<=r.high;
function clean(r){
 const q={t:r.t,end:r.end,date:r.date,close:r.close};
 if(finite(r.volume)&&r.volume>=0)q.volume=r.volume;
 // Never synthesize open/high/low from close for execution or indicators.
 if(finite(r.high)&&finite(r.low)&&0<r.low&&r.low<=r.close&&r.close<=r.high){
  Object.assign(q,{high:r.high,low:r.low});
  if(finite(r.open)&&r.low<=r.open&&r.open<=r.high)q.open=r.open;
 }
 return q;
}
function rows(source,now){
 const selected=(source?.rows||[]).filter(r=>validClose(r)&&r.end<now).sort((a,b)=>a.t-b.t);
 const times=new Set(),dates=new Set();
 for(const r of selected){if(times.has(r.t)||dates.has(r.date))throw Error('Duplicate study session');times.add(r.t);dates.add(r.date);}
 return selected.map(clean);
}
const mean=v=>v.length?v.reduce((s,x)=>s+x,0)/v.length:null;
function entry(history,symbol,now){
 const bars=history.slice(-253),last=bars.at(-1),v=bars.map(r=>r.close);
 const rets=v.slice(-85).slice(1).map((x,j)=>x/v.slice(-85)[j]-1),mu=mean(rets);
 const volatility=rets.length>=24?Math.sqrt(rets.reduce((s,x)=>s+(x-mu)**2,0)/(rets.length-1))*Math.sqrt(252):null;
 const average=n=>v.length>=n?mean(v.slice(-n)):null;
 // Match EOD snapshot inputs, including sample stdev and six-decimal rounding.
 const round=x=>finite(x)?Math.round(x*1e6)/1e6:null;
 return {symbol,status:'ready',fresh:!!last&&now-last.end<=5*DAY,asOf:last?.date,price:last?.close,
  history:bars.map(({t,end,...r})=>r),inputs:{ma20:round(average(20)),ma50:round(average(50)),ma200:round(average(200)),
   return1m:round(v.length>21?v.at(-1)/v.at(-22)-1:null),return3m:round(v.length>63?v.at(-1)/v.at(-64)-1:null),
   volatility4m:round(volatility),volume:last?.volume??null,
   avgVolume3m:mean(bars.slice(-63).map(r=>r.volume).filter(x=>finite(x)&&x>0))}};
}
function assess(history,symbol,credit,now){
 const e=entry(history,symbol,now),plan=T.plan(e,null,credit,now);
 return {entry:e,plan};
}
function manifest(market,now){
 if(!finite(now))throw Error('Study clock required');
 const universe=Object.keys(market.stocks||{}).filter(s=>s!=='SPY').sort()
  .map(symbol=>({symbol,sector:market.stocks[symbol].sector||'unknown'}));
 if(!universe.length||!market.stocks?.SPY)throw Error('Study requires stock universe and SPY');
 for(const {symbol} of [...universe,{symbol:'SPY'}])if(rows(market.stocks[symbol],now).length<205)
  throw Error('Study warmup missing: '+symbol);
 return {schemaVersion:1,version:VERSION,createdAt:now,sourceMarketGeneratedAt:market.generatedAt,
  ruleCommit:'bbafecc23d691894a52a8152c26e689353daa7f3',ruleGitBlob:'41faedc2be71bc67b03b12d5680eb53d1e2b7395',
  universe,benchmark:'SPY',initialUSD:10000,policy:copy(T.POLICY),costRisk:copy(P.CONFIG.stocks),
  execution:{sectorLimit:2,wholeShares:true,leverage:1,signalTTL:5*DAY,gapRangeMaximum:.5,
   pullbackCostRewardMinimum:1.3,fill:'next completed session whose open is after observation',
   sameBarPriority:'stop before target',missingOpen:'cancel entry; freeze held execution',
   dividends:false,tax:false,fx:false},
  holding:{reduce:'full exit at first open after observation',protect:'raise stop to prior 20-bar low, if below close',
   hold:'raise stop to prior 20-bar low, if below close',breakoutTarget:null,pullbackTarget:'signal prior 55-bar high',
   holdingTimeLimit:null},
  control:{name:'existing stock rules, same-start cash control',initialPositions:0,initialPending:0},
  safety:{forwardOnly:true,backfill:false,autoPromotion:false,replaceExistingAccount:false,liveTrading:false},
  sourceHashes:sourceHashes()};
}
function checkManifest(m){
 const rule=fs.readFileSync(path.join(__dirname,'entry-study-v1/technical-guide.cjs'));
 const gitBlob=crypto.createHash('sha1').update('blob '+rule.length+'\0').update(rule).digest('hex');
 if(gitBlob!=='41faedc2be71bc67b03b12d5680eb53d1e2b7395')throw Error('Study rules no longer match PR #19');
 if(m.version!==VERSION||canonical(m.sourceHashes)!==canonical(sourceHashes()))throw Error('Frozen study code changed; create a new study version');
 if(canonical(m.costRisk)!==canonical(P.CONFIG.stocks)||canonical(m.policy)!==canonical(T.POLICY))throw Error('Frozen study settings changed');
}
function account(now,role){
 const a=P.create('stocks',now);a.studyVersion=VERSION;a.studyRole=role;a.lastProcessed=now;a.startedAt=now;
 a.curve=[{at:now,equity:10000,cash:10000,exposure:0}];return a;
}
function snapshotExisting(a,costRisk=null){
 if(!a)return null;
 const report=P.report(a);
 return {equity:report.equity,cash:a.cash,positions:a.positions.map(p=>({symbol:p.symbol,qty:p.qty,mark:a.marks[p.symbol]??p.entry})),
  trades:a.trades.length,realized:report.realized,fees:a.fees,exposure:a.positions.reduce((s,p)=>s+p.qty*(a.marks[p.symbol]??p.entry),0),
  ruleVersion:a.version,costRisk:costRisk===null?null:copy(costRisk)};
}
function create(m,market,existing,existingCostRisk=null){
 checkManifest(m);
 const history=Object.fromEntries([...m.universe,{symbol:'SPY'}].map(({symbol})=>[symbol,rows(market.stocks[symbol],m.createdAt).slice(-260)]));
 const accounts={indicator:account(m.createdAt,'indicator'),control:account(m.createdAt,'control')};
 for(const a of Object.values(accounts)){
  a.marks=Object.fromEntries(m.universe.map(({symbol})=>[symbol,history[symbol].at(-1).close]));
  const price=history.SPY.at(-1).close;a.benchmark={symbol:'SPY',price,qty:m.initialUSD/(price*(1+m.costRisk.slip)*(1+m.costRisk.fee)),at:m.createdAt};
 }
 const anchor=snapshotExisting(existing,existingCostRisk);
 return {version:VERSION,createdAt:m.createdAt,lastSession:history.SPY.at(-1).t,history,accounts,
  frozenCostRisk:copy(m.costRisk),
  existingAnchor:anchor,existingObservations:anchor?[{at:m.createdAt,...anchor}]:[],warnings:[],qualityKey:null,
  observedSessions:0,missedObservationSessions:0,updatedAt:m.createdAt};
}
function event(a,type,now,data){a.events.push({id:'indicator:'+a.events.length,type,at:now,recordedAt:now,...copy(data)});}
function warn(state,text){if(!state.warnings.includes(text))state.warnings.push(text);}
function ingest(state,m,market,now){
 const unsafe={},quality=[];
 for(const {symbol} of [...m.universe,{symbol:'SPY'}]){
  const source=market.stocks?.[symbol];
  if(!source){unsafe[symbol]='source missing';quality.push(symbol+': source missing');continue;}
  if(source.errors?.length||source.revisions?.length){unsafe[symbol]='source errors or price revisions';quality.push(symbol+': '+unsafe[symbol]);}
  let incoming;
  try{incoming=rows(source,now);}catch(e){unsafe[symbol]=e.message;quality.push(symbol+': '+e.message);continue;}
  const known=new Map(state.history[symbol].map(r=>[r.t,r])),last=state.history[symbol].at(-1).t;
  for(const r of incoming){
   const prior=known.get(r.t);
   if(prior){
    const changed=['close','open','high','low'].some(k=>finite(prior[k])&&finite(r[k])&&Math.abs(r[k]/prior[k]-1)>.005);
    if(changed){unsafe[symbol]='material price revision';quality.push(symbol+': material price revision');}
    // First observed values remain the input basis, including close-only bars.
   }else if(r.t>last){state.history[symbol].push(r);}
  }
  if(!incoming.length||incoming.at(-1).t<state.history.SPY.at(-1).t){unsafe[symbol]='latest session missing';quality.push(symbol+': latest session missing');}
 }
 return {unsafe,quality:[...new Set(quality)].sort()};
}
function cancel(a,order,now,reason,signalAt){
 event(a,'cancel',now,{signalId:order.id,symbol:order.symbol,reason,signalAt:signalAt??order.at,levelBasis:order.levelBasis});
}
function execution(state,m,unsafe,now){
 const a=state.accounts.indicator,cfg=m.costRisk;
 const sessions=state.history.SPY.filter(r=>r.t>state.lastSession&&r.end>m.createdAt);
 for(const reference of sessions){
  const t=reference.t,bars={};
  for(const {symbol} of m.universe){
   const r=state.history[symbol].find(q=>q.t===t);
   if(r&&!unsafe[symbol]&&validOHLC(r))bars[symbol]=r;
   else if(a.positions.some(p=>p.symbol===symbol)){
    warn(state,symbol+': held execution unavailable; valuation and fills frozen');a.incompleteExecution=true;
   }
  }
  // Opening equity and purchases cannot use proceeds of intraday exits.
  for(const [s,r] of Object.entries(bars))a.marks[s]=r.open;
  for(const p of [...a.positions]){
   const r=bars[p.symbol];if(!r)continue;
   if(p.pendingStop&&r.t>=p.pendingStop.notBefore){
    p.stop=p.pendingStop.price;delete p.pendingStop;
    event(a,'stopApplied',now,{tradeId:p.id,symbol:p.symbol,price:p.stop,executionAt:r.t,levelBasis:p.levelBasis});
   }
   if(r.open<=p.stop)P.close(a,p,r.open,r.t,'손절 · 시가 갭',cfg,now,'open');
   else if(finite(p.target)&&r.open>=p.target)P.close(a,p,p.target,r.t,'익절 · 시가 목표 통과',cfg,now,'open');
   else if(p.exitPending&&r.t>=p.exitNotBefore)P.close(a,p,r.open,r.t,p.exitPending,cfg,now,'open');
  }
  const keep=[];
  for(const order of a.pending){
   if(t>order.expires){cancel(a,order,now,'신호 유효기간 만료');continue;}
   if(t<order.notBefore){keep.push(order);continue;}
   const r=bars[order.symbol];
   if(!r){cancel(a,order,now,unsafe[order.symbol]||'실제 OHLC가 없어 체결 취소');continue;}
   // Identical sizing, gap cap, fees, slippage, cash, share and sector limits
   // to the frozen stock engine. Only targetless breakouts waive its RR gate.
   const reason=P.enter(a,order,r,{...cfg,trend:order.pattern==='breakout'},now);
   if(reason){cancel(a,order,now,reason.replace('ATR','변동폭'));continue;}
   const p=a.positions.at(-1);Object.assign(p,{levelBasis:order.levelBasis,rangeBasis:order.rangeBasis,
    signalSnapshotId:order.signalSnapshotId});
   Object.assign(a.events.at(-1),{levelBasis:p.levelBasis,rangeBasis:p.rangeBasis,signalId:order.id});
  }
  a.pending=keep;
  for(const p of [...a.positions]){
   const r=bars[p.symbol];if(!r)continue;p.bars++;
   const stop=r.low<=p.stop,target=finite(p.target)&&r.high>=p.target;
   if(stop||target)P.close(a,p,stop?p.stop:p.target,r.end,
    stop?(target?'손절 · 같은 봉 목표 동시 도달':'손절'):'익절 · 눌림목 이전 55-bar high',cfg,now,'bar');
  }
  for(const [s,r] of Object.entries(bars))a.marks[s]=r.close;
  const eq=P.equity(a);a.highWater=Math.max(a.highWater,eq);a.maxDrawdown=Math.max(a.maxDrawdown,1-eq/a.highWater);
  a.curve.push({at:reference.end,equity:eq,cash:a.cash,benchmark:a.benchmark.qty*reference.close,
   exposure:a.positions.reduce((s,p)=>s+p.qty*(a.marks[p.symbol]??p.entry),0)});
  a.lastProcessed=t;
 }
}
function observe(state,m,market,credit,unsafe,now){
 const a=state.accounts.indicator,latest=state.history.SPY.at(-1);
 if(latest.t<=state.lastSession||latest.end<=m.createdAt)return [];
 const inputs=[];a.signals=[];
 for(const {symbol,sector} of m.universe){
  const history=state.history[symbol].filter(r=>r.end<=latest.end),last=history.at(-1);
  let result=assess(history,symbol,credit,now),plan=result.plan;
  if(unsafe[symbol]||!last||last.t!==latest.t){
   const reason=unsafe[symbol]||'같은 거래일 자료 없음';
   plan={...plan,code:'unavailable',reason,holding:{code:'unavailable',reason:'가격 자료 확인 필요'},
    setups:plan.setups.map(s=>({...s,state:'unavailable',reason}))};
  }
  const snapshotId=VERSION+':'+symbol+':'+latest.end;
  const summary={symbol,signalAt:last?.end??latest.end,code:plan.code,strategy:plan.strategy,reason:plan.reason,
   score:plan.ts,levelBasis:plan.levelBasis,levelBasisCode:plan.levelBasis==='일별 고가·저가'?'ohlc-high-low':'close-only-fallback',rangeBasis:plan.range.basis,range:plan.range.value,
   breakoutLevel:plan.breakoutLevel,exitLevel:plan.exitLevel,price:result.entry.price,
   stop:plan.stop,target:plan.target1,rr:plan.rr,riskPct:plan.riskPct,market:plan.market,
   relativeVolume:plan.indicators.relativeVolume,setups:plan.setups,holding:plan.holding,snapshotId};
  // Retain the full causal price history/inputs and point-in-time credit feed
  // in the immutable observation, so the exact assessment can be reproduced.
  const {history:priceHistory,...entryInputs}=result.entry;
  inputs.push({snapshotId,entry:entryInputs,historyHash:hash(priceHistory),summary});a.signals.push(summary);
  event(a,'assessment',now,summary);
  const held=a.positions.find(p=>p.symbol===symbol);
  if(held){
   event(a,'holding',now,{tradeId:held.id,...summary});
   if(plan.holding.code==='reduce'&&!held.exitPending){
    held.exitPending='PR #19 보유 대응 · 축소 검토';held.exitNotBefore=now;
    event(a,'exitSignal',now,{tradeId:held.id,symbol,reason:held.exitPending,signalAt:last.end,notBefore:now,levelBasis:plan.levelBasis});
   }else if(['hold','protect'].includes(plan.holding.code)&&finite(plan.exitLevel)&&plan.exitLevel<last.close&&plan.exitLevel>(held.pendingStop?.price??held.stop)){
    held.pendingStop={price:plan.exitLevel,notBefore:now};
    event(a,'stopUpdate',now,{tradeId:held.id,symbol,price:plan.exitLevel,notBefore:now,signalAt:last.end,levelBasis:plan.levelBasis});
   }
  }
  if(plan.code!=='buy')continue;
  const id=snapshotId+':'+plan.strategy;
  event(a,'signal',now,{signalId:id,...summary});
  if(held||a.pending.some(q=>q.symbol===symbol)){
   event(a,'orderSkipped',now,{signalId:id,symbol,reason:held?'이미 보유 중':'기존 주문 대기 중',levelBasis:plan.levelBasis});continue;
  }
  if(now>=last.end+m.execution.signalTTL){event(a,'orderSkipped',now,{signalId:id,symbol,reason:'관측 시 유효기간 만료',levelBasis:plan.levelBasis});continue;}
  const order={id,symbol,sector,side:'long',pattern:plan.strategy,reason:plan.reason,at:last.end,price:last.close,
   stop:plan.stop,target:plan.target1,atr:plan.range.value,rank:plan.ts,holdBars:Number.MAX_SAFE_INTEGER,
   levelBasis:plan.levelBasis,rangeBasis:plan.range.basis,signalSnapshotId:snapshotId,
   createdAt:now,notBefore:Math.max(now,last.end+1),expires:last.end+m.execution.signalTTL};
  a.pending.push(order);event(a,'order',now,{...order,signalId:id});
 }
 a.pending.sort((x,y)=>y.rank-x.rank||x.symbol.localeCompare(y.symbol));
 return inputs;
}
function advance(prior,m,market,credit,existing,now,existingCostRisk=null){
 checkManifest(m);if(now<prior.updatedAt)throw Error('Study clock went backwards');
 const state=copy(prior),counts=Object.fromEntries(Object.entries(state.accounts).map(([k,a])=>[k,a.events.length]));
 const {unsafe,quality}=ingest(state,m,market,now),qualityKey=hash(quality);
 if(unsafe.SPY){quality.push('benchmark unavailable; study settlement paused');warn(state,'SPY unavailable: settlement paused');}
 const latest=state.history.SPY.at(-1),newSession=!unsafe.SPY&&latest.t>state.lastSession&&latest.end>m.createdAt;
 let observations=[];
 if(newSession){
  const skipped=state.history.SPY.filter(r=>r.t>state.lastSession&&r.end>m.createdAt&&r.t<latest.t);
  if(skipped.length){
   state.missedObservationSessions+=skipped.length;warn(state,'Missed observation sessions: compare returns with catch-up limitations');
   event(state.accounts.indicator,'observationGap',now,{skippedSignalSessions:skipped.map(r=>r.date)});
  }
  execution(state,m,unsafe,now);
  const sources=Object.fromEntries([...m.universe,{symbol:'SPY'}].map(({symbol,sector})=>{
   const executionMissing=symbol!=='SPY'&&state.history[symbol].some(r=>r.t>state.accounts.control.lastProcessed&&!validOHLC(r));
   return [symbol,{rows:state.history[symbol],sector,revisions:unsafe[symbol]||executionMissing?['study data quality']:[],errors:[]}];
  }));
  const before=state.accounts.control;
  state.accounts.control=P.run(before,{stocks:sources},{mode:'forward',now});
  if(latest.t<=m.createdAt){
   // First completed session can have opened before a midday study start.
   // No genesis order/holding existed, so only its post-start close is observed.
   const a=state.accounts.control;
   a.curve.push({at:latest.end,equity:P.equity(a),cash:a.cash,exposure:0,benchmark:a.benchmark.qty*latest.close});
   a.lastProcessed=latest.t;
  }
  for(const e of state.accounts.control.events.slice(counts.control))if(e.type==='signal')Object.assign(e,
   {levelBasis:e.reason?.includes('20일 종가 돌파')?'종가':'EMA20·일별 저가',rangeBasis:'wilder-atr14'});
  for(const {symbol} of m.universe){
   const q=state.accounts.control.signals.find(q=>q.symbol===symbol)||{reason:'같은 거래일 자료 없음'},a=state.accounts.control;
   const summary={symbol,signalAt:q.at??latest.end,reason:q.reason,
    eligible:!!q.side,pattern:q.reason?.includes('20일 종가 돌파')?'legacy20Breakout':'legacyPullback',
    levelBasis:q.reason?.includes('20일 종가 돌파')?'종가':'EMA20·일별 저가',rangeBasis:'wilder-atr14'};
   a.events.push({id:'control-assessment:'+a.events.length,type:'assessment',at:now,recordedAt:now,...summary});
   if(q.side)a.events.push({id:'control-opportunity:'+a.events.length,type:'opportunity',at:now,recordedAt:now,...summary});
  }
  // Explicit holding snapshots supplement the old engine's price-driven exits.
  for(const p of state.accounts.control.positions)state.accounts.control.events.push({id:'control-holding:'+state.accounts.control.events.length,
   type:'holding',at:now,recordedAt:now,tradeId:p.id,symbol:p.symbol,stop:p.stop,target:p.target,exitPending:p.exitPending||null});
  observations=observe(state,m,market,credit,unsafe,now);
  state.lastSession=latest.t;state.observedSessions++;
  const observed=snapshotExisting(existing,existingCostRisk);if(observed)state.existingObservations.push({at:latest.end,...observed});
 }
 // Cancel previously posted orders on observed source failure, even when no
 // benchmark bar is available. This never retroactively changes a fill.
 for(const order of [...state.accounts.indicator.pending])if(unsafe[order.symbol]||now>=order.expires){
  cancel(state.accounts.indicator,order,now,unsafe[order.symbol]||'신호 유효기간 만료');
  state.accounts.indicator.pending=state.accounts.indicator.pending.filter(q=>q.id!==order.id);
 }
 if(state.qualityKey!==qualityKey){
  event(state.accounts.indicator,'dataQuality',now,{issues:quality});state.qualityKey=qualityKey;
 }
 const deltas=Object.fromEntries(Object.entries(state.accounts).map(([k,a])=>[k,a.events.slice(counts[k])]));
 const changed=newSession||Object.values(deltas).some(v=>v.length);
 if(!changed)return {state:prior,events:{indicator:[],control:[]},inputs:null,changed:false};
 state.updatedAt=now;
 for(const [k,a] of Object.entries(state.accounts)){
  if(canonical(a.trades.slice(0,prior.accounts[k].trades.length))!==canonical(prior.accounts[k].trades))throw Error('Closed study trades changed');
  if(canonical(a.events.slice(0,counts[k]))!==canonical(prior.accounts[k].events))throw Error('Recorded study events changed');
 }
 return {state,events:deltas,changed:true,inputs:{marketGeneratedAt:market.generatedAt,credit:copy(credit),
  observations,quality,existing:snapshotExisting(existing,existingCostRisk)}};
}
function statistics(a){
 const r=P.report(a),observed=a.events.filter(e=>e.type==='assessment');
 const signals=a.events.filter(e=>e.type===(a.studyRole==='control'?'opportunity':'signal'));
 const exposure=a.curve.slice(1).map(q=>q.equity>0?q.exposure/q.equity:0);
 const bySetup={};
 const isControl=a.studyRole==='control',setupOf=t=>isControl?(t.reason?.includes('20일 종가 돌파')?'legacy20Breakout':'legacyPullback'):t.strategy||t.pattern;
 for(const setup of isControl?['legacy20Breakout','legacyPullback']:['breakout','pullback']){
  const trades=a.trades.filter(t=>setupOf(t)===setup);
  bySetup[setup]={signals:signals.filter(e=>setupOf(e)===setup).length,orders:a.events.filter(e=>e.type===(isControl?'signal':'order')&&setupOf(e)===setup).length,
   trades:trades.length,net:trades.reduce((s,t)=>s+t.net,0)};
 }
 const byLevelBasis={};
 if(!isControl)for(const basis of ['일별 고가·저가','종가']){
  const trades=a.trades.filter(t=>t.levelBasis===basis);
  byLevelBasis[basis]={signals:signals.filter(e=>e.levelBasis===basis).length,trades:trades.length,net:trades.reduce((s,t)=>s+t.net,0)};
 }
 return {equity:r.equity,return:r.return,realized:r.realized,unrealized:r.unrealized,fees:a.fees,slippage:a.slippage,
  trades:a.trades.length,positions:a.positions.length,pending:a.pending.length,winRate:r.winRate,maxDrawdown:a.maxDrawdown,
  assessedStockSessions:observed.length,signals:signals.length,signalsPer100StockSessions:observed.length?100*signals.length/observed.length:null,
  orders:a.events.filter(e=>e.type==='order').length,entries:a.events.filter(e=>e.type==='entry').length,
  cancellations:a.events.filter(e=>e.type==='cancel').length,sessionAverageExposure:mean(exposure),
  maximumExposure:exposure.length?Math.max(...exposure):0,currentExposure:r.equity>0?a.positions.reduce((s,p)=>s+p.qty*(a.marks[p.symbol]??p.entry),0)/r.equity:0,
  incompleteExecution:!!a.incompleteExecution,bySetup,byLevelBasis};
}
function comparison(state){
 const indicator=statistics(state.accounts.indicator),control=statistics(state.accounts.control);
 control.signalDefinition='all observed qualifying stock sessions';indicator.signalDefinition='all observed qualifying stock sessions';
 control.orders=state.accounts.control.events.filter(e=>e.type==='signal').length;
 const obs=state.existingObservations,anchor=state.existingAnchor,last=obs.at(-1);
 let existing=null;
 if(anchor&&last){
  const equities=obs.map(q=>q.equity);let high=equities[0],dd=0;
  for(const eq of equities){high=Math.max(high,eq);dd=Math.max(dd,1-eq/high);}
  existing={startEquity:anchor.equity,startPositions:anchor.positions.length,returnSinceStart:last.equity/anchor.equity-1,
   realizedSinceStart:last.realized-anchor.realized,newClosedTrades:last.trades-anchor.trades,
   feesSinceStart:last.fees-anchor.fees,maxDrawdownSinceStart:dd,
   sessionAverageExposure:mean(obs.slice(1).map(q=>q.equity>0?q.exposure/q.equity:0)),
   currentExposure:last.equity>0?last.exposure/last.equity:0,
   sameCostRiskAssumptions:obs.every(q=>q.costRisk!==null&&canonical(q.costRisk)===canonical(state.frozenCostRisk)),
   interpretation:'descriptive: existing positions and pending orders at start; not a same-start strategy comparison'};
 }
 return {indicator,control,existing,observedSessions:state.observedSessions,
  missedObservationSessions:state.missedObservationSessions,
  executionComparable:!indicator.incompleteExecution&&!control.incompleteExecution&&!state.missedObservationSessions,
  evidenceStatus:state.observedSessions?'collecting forward evidence':'awaiting first new session',
  performanceValidated:false,autoPromotion:false};
}
module.exports={VERSION,canonical,hash,sourceHashes,manifest,checkManifest,create,advance,comparison,entry,assess,validOHLC,snapshotExisting};
