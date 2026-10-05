'use strict';
// Retrospective research only. Never writes production data or forward ledgers.
const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto');
const T=require('./entry-study-v1/technical-guide.cjs');
const P=require('./entry-study-v1/paper-engine.cjs');
const Study=require('./entry_study.cjs');
const ROOT=path.resolve(__dirname,'..'),DAY=86400000,VERSION='entry-context-v1-retrospective-v1';
const WAIT=new Set(['breakout','pullback','riskwait']),finite=Number.isFinite;
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const mean=a=>a.length?a.reduce((s,x)=>s+x,0)/a.length:null;
const ticker=(a,b)=>a.localeCompare(b);
const compare=(a,b)=>b.plan.ts-a.plan.ts||ticker(a.symbol,b.symbol);

function scenarioFeed(status,date){
 const generatedAt=date+'T23:59:59.000Z';
 return {generatedAt,credit:{status},indicators:['NFCI','STLFSI4','DRTSCILM','FUNDING'].map(id=>
  ({id,status:'ready',asOf:date,maxAgeDays:id==='DRTSCILM'?150:id==='FUNDING'?5:16})),
  researchAssumption:'fixed '+status+' scenario, not historical observed credit'};
}
function makeEntry(history,symbol,now){
 const e=Study.entry(history,symbol,now),last=history.at(-1);
 // Production rounds the current CSV price while preserving quote precision
 // in history. Reusing the forward adapter's raw price can change >= and >.
 e.price=finite(last?.signalPrice)?last.signalPrice:finite(e.price)?Number(e.price.toFixed(6)):null;
 const volume=history.slice(-63).map(r=>r.volume).filter(x=>finite(x)&&x>=0);
 e.inputs.avgVolume3m=volume.length?Math.trunc(mean(volume)):null;
 return e;
}
function assessPrefix(source,symbol,i,status){
 const last=source.rows[i],now=Date.parse(last.date+'T23:59:59Z');
 const entry=makeEntry(source.rows.slice(Math.max(0,i-252),i+1),symbol,now);
 return {entry,plan:T.plan(entry,null,scenarioFeed(status,last.date),now),symbol,index:i};
}
function indexData(data){
 if(!data.stocks?.SPY)throw Error('SPY required');
 const indexed={};
 for(const [symbol,s] of Object.entries(data.stocks)){
  const byDate=new Map();let previous='';
  for(let i=0;i<s.rows.length;i++){
   const r=s.rows[i];
   if(!Study.validOHLC(r)||r.date<=previous||r.date>data.cutoff)throw Error('Invalid OHLC/session: '+symbol+' '+r.date);
   if(data.schemaVersion>=2&&!finite(r.signalPrice))throw Error('Rounded production signal price missing');
   if(r.volume!==null&&r.volume!==undefined&&(!finite(r.volume)||r.volume<0))throw Error('Invalid volume');
   previous=r.date;byDate.set(r.date,i);
  }
  indexed[symbol]={...s,byDate};
 }
 return indexed;
}
function outcome(indexed,symbol,date,horizon,cfg=P.CONFIG.stocks){
 const stock=indexed[symbol],spy=indexed.SPY,si=stock.byDate.get(date),bi=spy.byDate.get(date);
 if(si===undefined||bi===undefined)return {excluded:'missingSignal'};
 if(bi+horizon>=spy.rows.length||si+horizon>=stock.rows.length)return {excluded:'immature'};
 const bars=stock.rows.slice(si+1,si+horizon+1),reference=spy.rows.slice(bi+1,bi+horizon+1);
 if(bars.some((r,i)=>r.date!==reference[i].date))return {excluded:'missingSession'};
 const cost=(1-cfg.slip)*(1-cfg.fee)/((1+cfg.slip)*(1+cfg.fee));
 const net=bars.at(-1).close/bars[0].open*cost-1;
 const benchmark=reference.at(-1).close/reference[0].open*cost-1;
 return {symbol,date,entryDate:bars[0].date,endDate:bars.at(-1).date,net,benchmark,excess:net-benchmark,
  adverse:Math.min(...bars.map(r=>r.low))/bars[0].open-1};
}
function observations(){return Object.fromEntries([20,63].map(h=>[h,{rows:[],excluded:{}}]));}
function addObservation(group,indexed,symbol,date){
 for(const h of [20,63]){
  const q=outcome(indexed,symbol,date,h);
  if(q.excluded)group[h].excluded[q.excluded]=(group[h].excluded[q.excluded]||0)+1;
  else group[h].rows.push(q);
 }
}
function quantile(v,q){
 if(!v.length)return null;const a=[...v].sort((x,y)=>x-y),i=(a.length-1)*q;
 return a[Math.floor(i)]+(a[Math.ceil(i)]-a[Math.floor(i)])*(i-Math.floor(i));
}
function summarizeObservations(group){
 return Object.fromEntries(Object.entries(group).map(([h,{rows,excluded}])=>{
  const dates=new Map();
  for(const r of rows){if(!dates.has(r.date))dates.set(r.date,[]);dates.get(r.date).push(r);}
  const daily=[...dates.values()].map(a=>({net:mean(a.map(r=>r.net)),excess:mean(a.map(r=>r.excess))}));
  return [h,{observations:rows.length,signalDates:dates.size,excluded,meanNet:mean(rows.map(r=>r.net)),
   medianNet:quantile(rows.map(r=>r.net),.5),winRate:mean(rows.map(r=>Number(r.net>0))),
   meanBenchmark:mean(rows.map(r=>r.benchmark)),meanExcess:mean(rows.map(r=>r.excess)),
   dateBalancedMeanNet:mean(daily.map(r=>r.net)),dateBalancedMeanExcess:mean(daily.map(r=>r.excess)),
   p10Net:quantile(rows.map(r=>r.net),.1),meanAdverse:mean(rows.map(r=>r.adverse)),p10Adverse:quantile(rows.map(r=>r.adverse),.1)}];
 }));
}
function newAccount(first){
 const a=P.create('stocks',first.t);
 a.curve=[{date:first.date,at:first.t,equity:a.initial,cash:a.initial,exposure:0,phase:'beforeFirstOpen'}];
 a.rejections={};a.missingHeldSessions=0;return a;
}
function execute(a,indexed,reference){
 const cfg=P.CONFIG.stocks,date=reference.date,bars={};
 for(const [s,source] of Object.entries(indexed)){
  const i=source.byDate.get(date);if(i!==undefined)bars[s]=source.rows[i];
 }
 for(const p of a.positions)if(!bars[p.symbol])a.missingHeldSessions++;
 for(const [s,r] of Object.entries(bars))a.marks[s]=r.open;
 for(const p of [...a.positions]){
  const r=bars[p.symbol];if(!r)continue;
  if(p.pendingStop&&r.t>=p.pendingStop.notBefore){p.stop=p.pendingStop.price;delete p.pendingStop;}
  if(r.open<=p.stop)P.close(a,p,r.open,r.t,'stop gap',cfg,r.end,'open');
  else if(finite(p.target)&&r.open>=p.target)P.close(a,p,p.target,r.t,'target gap',cfg,r.end,'open');
  else if(p.exitPending&&r.t>=p.exitNotBefore)P.close(a,p,r.open,r.t,'holding reduce',cfg,r.end,'open');
 }
 const keep=[];
 for(const order of a.pending){
  let reason=null;
  if(reference.t>order.expires)reason='expired';
  else if(reference.t<order.notBefore){keep.push(order);continue;}
  else if(!bars[order.symbol])reason='missing open';
  else reason=P.enter(a,order,bars[order.symbol],{...cfg,trend:order.pattern==='breakout'},reference.end);
  if(reason)a.rejections[reason]=(a.rejections[reason]||0)+1;
 }
 a.pending=keep;
 for(const p of [...a.positions]){
  const r=bars[p.symbol];if(!r)continue;p.bars++;
  const stop=r.low<=p.stop,target=finite(p.target)&&r.high>=p.target;
  if(stop||target)P.close(a,p,stop?p.stop:p.target,r.end,stop?(target?'stop before same-bar target':'stop'):'pullback target',cfg,r.end,'bar');
 }
 for(const [s,r] of Object.entries(bars))a.marks[s]=r.close;
 const equity=P.equity(a);a.highWater=Math.max(a.highWater,equity);a.maxDrawdown=Math.max(a.maxDrawdown,1-equity/a.highWater);
 a.curve.push({date,at:reference.end,equity,cash:a.cash,
  exposure:a.positions.reduce((s,p)=>s+p.qty*(a.marks[p.symbol]??p.entry),0)});
}
function observeAccount(a,assessments,date){
 for(const q of assessments){
  const {plan,symbol,entry}=q,held=a.positions.find(p=>p.symbol===symbol);
  const signalAt=Date.parse(date+'T23:59:59Z');
  if(held){
   if(plan.holding.code==='reduce'&&!held.exitPending){held.exitPending='reduce';held.exitNotBefore=signalAt;}
   else if(['hold','protect'].includes(plan.holding.code)&&finite(plan.exitLevel)&&plan.exitLevel<entry.price&&plan.exitLevel>(held.pendingStop?.price??held.stop)){
    held.pendingStop={price:plan.exitLevel,notBefore:signalAt};
   }
  }
 }
 for(const q of assessments.filter(q=>q.plan.code==='buy').sort(compare)){
  const {symbol,entry,plan}=q;
  if(a.positions.some(p=>p.symbol===symbol)||a.pending.some(p=>p.symbol===symbol))continue;
  const at=Date.parse(date+'T23:59:59Z');
  a.pending.push({id:VERSION+':'+symbol+':'+date,symbol,sector:q.sector,side:'long',pattern:plan.strategy,
   reason:plan.reason,at,createdAt:at,notBefore:at+1,expires:at+5*DAY,price:entry.price,stop:plan.stop,
   target:plan.target1,atr:plan.range.value,rank:plan.ts,holdBars:Number.MAX_SAFE_INTEGER});
 }
 a.pending.sort((x,y)=>y.rank-x.rank||ticker(x.symbol,y.symbol));
}
function annualAccounts(a,benchmark){
 const rows=a.curve.filter(r=>r.phase!=='beforeFirstOpen'),years={};let previous=a.initial,previousBenchmark=a.initial;
 for(const r of rows){
  const year=r.date.slice(0,4);
  if(!years[year])years[year]={start:previous,end:previous,benchmarkStart:previousBenchmark,benchmarkEnd:previousBenchmark,
   high:previous,maxDrawdown:0,exposure:[],sessions:0};
  const y=years[year];y.end=r.equity;y.benchmarkEnd=benchmark.get(r.date);y.high=Math.max(y.high,r.equity);
  y.maxDrawdown=Math.max(y.maxDrawdown,1-r.equity/y.high);y.exposure.push(r.exposure/r.equity);y.sessions++;
  previous=r.equity;previousBenchmark=y.benchmarkEnd;
 }
 return Object.fromEntries(Object.entries(years).map(([year,y])=>[year,{sessions:y.sessions,return:y.end/y.start-1,
  benchmarkReturn:y.benchmarkEnd/y.benchmarkStart-1,maxDrawdown:y.maxDrawdown,meanExposure:mean(y.exposure),
  closedTrades:a.trades.filter(t=>new Date(t.exitAt).getUTCFullYear()===Number(year)).length}]));
}
function summarizeAccount(a,reference){
 const cfg=P.CONFIG.stocks,first=reference[0],last=reference.at(-1),years=(last.end-first.t)/(365.25*DAY);
 const spyQty=a.initial/(first.open*(1+cfg.slip)*(1+cfg.fee));
 const benchmark=new Map(reference.map(r=>[r.date,spyQty*r.close]));
 const mark=P.equity(a),liquidation=mark-a.positions.reduce((s,p)=>s+p.qty*a.marks[p.symbol]*(1-(1-cfg.slip)*(1-cfg.fee)),0);
 const report=P.report(a),rows=a.curve.filter(r=>!r.phase);
 let spyHigh=a.initial,spyDD=0;for(const v of benchmark.values()){spyHigh=Math.max(spyHigh,v);spyDD=Math.max(spyDD,1-v/spyHigh);}
 return {initial:a.initial,markEquity:mark,markReturn:mark/a.initial-1,liquidationEquivalentEquity:liquidation,
  liquidationEquivalentReturn:liquidation/a.initial-1,cagr:(liquidation/a.initial)**(1/years)-1,
  maxDrawdown:a.maxDrawdown,meanExposure:mean(rows.map(r=>r.exposure/r.equity)),
  sessionsInvested:rows.filter(r=>r.exposure>0).length,closedTrades:a.trades.length,
  entries:a.trades.length+a.positions.length,winRate:report.winRate,profitFactor:report.profitFactor,
  fees:a.fees,slippage:a.slippage,openPositions:a.positions.length,missingHeldSessions:a.missingHeldSessions,
  rejections:a.rejections,annual:annualAccounts(a,benchmark),
  benchmark:{symbol:'SPY',basis:'price-only, dividends excluded',markReturn:benchmark.get(last.date)/a.initial-1,
   netReturn:benchmark.get(last.date)*(1-cfg.slip)*(1-cfg.fee)/a.initial-1,
   cagr:(benchmark.get(last.date)*(1-cfg.slip)*(1-cfg.fee)/a.initial)**(1/years)-1,maxDrawdown:spyDD}};
}
function run(data,{start='2017-10-02',statuses=['stable','watch'],onProgress=()=>{}}={}){
 const indexed=indexData(data),reference=indexed.SPY.rows.filter(r=>r.date>=start);
 if(!reference.length)throw Error('No evaluation sessions');
 const symbols=Object.keys(indexed).sort(ticker);
 const states=Object.fromEntries(statuses.map(s=>[s,{account:newAccount(reference[0]),daily:[],
  previousBuy:new Set(),episodes:0,states:{},allBuy:observations(),top3:observations(),waitingTop3:observations()}]));
 for(let di=0;di<reference.length;di++){
  const ref=reference[di];
  for(const s of statuses)execute(states[s].account,indexed,ref);
  const assessed=Object.fromEntries(statuses.map(s=>[s,[]]));
  for(const symbol of symbols){
   const source=indexed[symbol],i=source.byDate.get(ref.date);if(i===undefined)continue;
   const now=Date.parse(ref.date+'T23:59:59Z');
   const entry=makeEntry(source.rows.slice(Math.max(0,i-252),i+1),symbol,now);
   for(const s of statuses){
    const plan=T.plan(entry,null,scenarioFeed(s,ref.date),now);
    assessed[s].push({symbol,index:i,sector:source.sector,entry,plan});
   }
  }
  for(const status of statuses){
   const state=states[status],rows=assessed[status],buy=rows.filter(q=>q.plan.code==='buy').sort(compare);
   const waiting=buy.length?[]:rows.filter(q=>WAIT.has(q.plan.code)).sort(compare).slice(0,3);
   const codes={};for(const q of rows){codes[q.plan.code]=(codes[q.plan.code]||0)+1;state.states[q.plan.code]=(state.states[q.plan.code]||0)+1;}
   for(const q of buy){addObservation(state.allBuy,indexed,q.symbol,ref.date);if(!state.previousBuy.has(q.symbol))state.episodes++;}
   for(const q of buy.slice(0,3))addObservation(state.top3,indexed,q.symbol,ref.date);
   for(const q of waiting)addObservation(state.waitingTop3,indexed,q.symbol,ref.date);
   state.previousBuy=new Set(buy.map(q=>q.symbol));
   state.daily.push({date:ref.date,available:rows.length,eligible:rows.filter(q=>q.entry.inputs.ma200>0).length,
    buy:buy.length,top3:buy.slice(0,3).map(q=>q.symbol),waiting:waiting.map(q=>({symbol:q.symbol,code:q.plan.code})),codes});
   observeAccount(state.account,rows,ref.date);
  }
  if(di%100===0||di===reference.length-1)onProgress({completed:di+1,sessions:reference.length,date:ref.date});
 }
 const scenarios={};
 for(const status of statuses){
  const state=states[status],counts=state.daily.map(r=>r.buy),annual={};
  for(const r of state.daily){
   const y=r.date.slice(0,4);if(!annual[y])annual[y]={sessions:0,zero:0,one:0,two:0,threeOrMore:0,totalSignals:0};
   const a=annual[y];a.sessions++;a.totalSignals+=r.buy;a[r.buy===0?'zero':r.buy===1?'one':r.buy===2?'two':'threeOrMore']++;
  }
  scenarios[status]={frequency:{sessions:counts.length,zeroDays:counts.filter(n=>n===0).length,
   oneDays:counts.filter(n=>n===1).length,twoDays:counts.filter(n=>n===2).length,threeOrMoreDays:counts.filter(n=>n>=3).length,
   zeroShare:mean(counts.map(n=>Number(n===0))),meanBuyCount:mean(counts),medianBuyCount:quantile(counts,.5),
   totalSignalObservations:counts.reduce((s,n)=>s+n,0),buyEpisodes:state.episodes,annual},
   stateCounts:state.states,allBuyOutcomes:summarizeObservations(state.allBuy),top3Outcomes:summarizeObservations(state.top3),
   waitingTop3Outcomes:summarizeObservations(state.waitingTop3),portfolio:summarizeAccount(state.account,reference),
   latest:state.daily.at(-1)};
 }
 return {version:VERSION,start:reference[0].date,end:reference.at(-1).date,symbols:symbols.length,
  policy:T.POLICY,costRisk:P.CONFIG.stocks,marketAssumption:'fixed scenarios; no historical credit reconstruction',
  scenarios,details:states};
}
function csv(rows,columns){
 return columns.join(',')+'\n'+rows.map(r=>columns.map(k=>{const x=String(r[k]??'');return /[,"\n]/.test(x)?'"'+x.replaceAll('"','""')+'"':x;}).join(',')).join('\n')+'\n';
}
function auditLatest(data,forecasts,market){
 const A=require('../assets/stock-assessment.js'),now=Date.parse(market.generatedAt)+1;
 const expected=A.all(forecasts,market,null,126,now),counts={},mismatches=[];
 for(const [symbol,source] of Object.entries(data.stocks)){
  const e=makeEntry(source.rows.slice(-253),symbol,now),plan=T.plan(e,null,market,now),old=expected[symbol];
  counts[plan.code]=(counts[plan.code]||0)+1;
  if(!old||old.plan.code!==plan.code||old.score!==plan.ts)mismatches.push({symbol,code:plan.code,score:plan.ts,
   publishedCode:old?.plan.code,publishedScore:old?.score});
 }
 return {priceGeneratedAt:forecasts.generatedAt,marketGeneratedAt:market.generatedAt,
  evaluatedAt:new Date(now).toISOString(),market:T.marketState(market,now),compared:Object.keys(data.stocks).length,
  publishedSymbols:Object.keys(expected).length,counts,mismatches};
}
function main(){
 const arg=k=>{const i=process.argv.indexOf(k);return i<0?undefined:process.argv[i+1];};
 const input=arg('--input')||path.join(ROOT,'research/history/entry-backtest-2026-10-04/prices.json.gz');
 const out=arg('--output')||path.join(ROOT,'research/entry-backtest/2026-10-04');
 const raw=zlib.gunzipSync(fs.readFileSync(input)),data=JSON.parse(raw);
 if(!fs.readFileSync(path.join(__dirname,'entry-study-v1/technical-guide.cjs')).equals(fs.readFileSync(path.join(ROOT,'assets/technical-guide.js'))))throw Error('Frozen rule differs from production; do not silently substitute');
 let latestSnapshotAudit;
 const forecastPath=path.join(ROOT,'forecasts/latest.json'),marketPath=path.join(ROOT,'market/latest.json');
 if(fs.existsSync(forecastPath)&&fs.existsSync(marketPath)){
  const forecasts=JSON.parse(fs.readFileSync(forecastPath)),market=JSON.parse(fs.readFileSync(marketPath));
  if(Object.values(forecasts.stocks).every(e=>e.asOf===data.cutoff)){
   latestSnapshotAudit=auditLatest(data,forecasts,market);
   latestSnapshotAudit.forecastsSHA256=sha(fs.readFileSync(forecastPath));
   latestSnapshotAudit.marketSHA256=sha(fs.readFileSync(marketPath));
   if(latestSnapshotAudit.mismatches.length)throw Error('Current snapshot parity failed: '+JSON.stringify(latestSnapshotAudit.mismatches));
   process.stderr.write(JSON.stringify({latestSnapshotParity:'passed',symbols:latestSnapshotAudit.compared})+'\n');
  }
 }
 const result=run(data,{start:arg('--start')||'2017-10-02',onProgress:p=>process.stderr.write(JSON.stringify(p)+'\n')});
 const details=result.details;delete result.details;
 result.input={path:path.relative(ROOT,input),sha256:sha(raw),universeSHA256:data.universeSHA256,cutoff:data.cutoff,basis:data.basis};
 result.input.homeUniverseSHA256=data.homeUniverseSHA256;
 if(latestSnapshotAudit)result.latestSnapshotAudit=latestSnapshotAudit;
 result.sourceHashes=Object.fromEntries(['scripts/backtest_entry_rules.cjs','scripts/collect_entry_backtest.py','scripts/entry_study.cjs',
  'scripts/entry-study-v1/technical-guide.cjs','scripts/entry-study-v1/paper-engine.cjs'].map(p=>[p,sha(fs.readFileSync(path.join(ROOT,p)))]));
 fs.mkdirSync(out,{recursive:true});
 fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(result,null,2)+'\n');
 for(const [status,s] of Object.entries(details)){
  fs.writeFileSync(path.join(out,status+'-daily.csv'),csv(s.daily.map(r=>({date:r.date,available:r.available,eligible:r.eligible,buy:r.buy,
   top3:r.top3.join('|'),waiting:r.waiting.map(q=>q.symbol+':'+q.code).join('|'),...r.codes})),
   ['date','available','eligible','buy','top3','waiting','breakout','pullback','riskwait','overextended','confirm','watch','avoid','unavailable']));
  fs.writeFileSync(path.join(out,status+'-curve.csv'),csv(s.account.curve,['date','at','phase','equity','cash','exposure']));
  fs.writeFileSync(path.join(out,status+'-trades.csv'),csv(s.account.trades,['symbol','sector','pattern','signalAt','entryAt','entry','qty','stop','target','exitAt','exit','exitReason','net','entryFee','exitFee','bars']));
  fs.writeFileSync(path.join(out,status+'-open.json'),JSON.stringify(s.account.positions.map(p=>({...p,mark:s.account.marks[p.symbol]})),null,2)+'\n');
 }
 process.stdout.write(JSON.stringify({start:result.start,end:result.end,symbols:result.symbols,
  scenarios:Object.fromEntries(Object.entries(result.scenarios).map(([s,r])=>[s,{frequency:r.frequency,portfolio:r.portfolio,top3:r.top3Outcomes,latest:r.latest}]))})+'\n');
}
module.exports={VERSION,scenarioFeed,makeEntry,assessPrefix,indexData,outcome,execute,observeAccount,newAccount,run,compare,auditLatest};
if(require.main===module)main();
