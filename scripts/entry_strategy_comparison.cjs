'use strict';
// Research only: frozen price vintage, three fixed families, no production writes.
const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto');
const B=require('./backtest_entry_rules.cjs'),P=require('./entry-study-v1/paper-engine.cjs');
const ROOT=path.resolve(__dirname,'..'),DAY=86400000,VERSION='entry-strategy-comparison-v1';
const INPUT_SHA='0307d3266187abea5e008fbaefd71a447d78298365ff41d2f7939516a12cf92a';
const METHODS=Object.freeze([
 Object.freeze({id:'channel55',name:'55일 채널 돌파',holdBars:null,targetless:true}),
 Object.freeze({id:'pullback20',name:'20일선 눌림 반등',holdBars:84,targetless:false}),
 Object.freeze({id:'rsi2',name:'RSI(2) 평균회귀',holdBars:10,targetless:true})
]);
const PERIODS=Object.freeze({early:{start:'2017-10-02',end:'2022-12-30'},recent:{start:'2023-01-03',end:'2026-10-02'}});
const cfgFor=stress=>({...P.CONFIG.stocks,fee:P.CONFIG.stocks.fee*(stress?2:1),slip:P.CONFIG.stocks.slip*(stress?2:1)});
const mean=a=>a.length?a.reduce((s,x)=>s+x,0)/a.length:null;
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const compare=(a,b)=>b.rank-a.rank||a.symbol.localeCompare(b.symbol);
const inPeriod=(d,p)=>d>=p.start&&d<=p.end;

function features(rows,calendar){
 const out=[],sum=[0],tr=[0];let gain=0,loss=0,consecutive=0,previousCalendar;
 for(let i=0;i<rows.length;i++){
  const r=rows[i],p=rows[i-1];sum.push(sum[i]+r.close);
  const range=p?Math.max(r.high-r.low,Math.abs(r.high-p.close),Math.abs(r.low-p.close)):0;
  tr.push(tr[i]+range);
  const ci=calendar?.get(r.date);
  consecutive=calendar?(ci!==undefined&&previousCalendar!==undefined&&ci===previousCalendar+1?consecutive+1:ci===undefined?0:1):i+1;
  previousCalendar=ci;
  let rsi2=null;
  if(i){
   const change=r.close-p.close,g=Math.max(change,0),l=Math.max(-change,0);
   if(i<=2){gain+=g/2;loss+=l/2;}else{gain=(gain+g)/2;loss=(loss+l)/2;}
   if(i>=2)rsi2=gain===0&&loss===0?50:loss===0?100:100-100/(1+gain/loss);
  }
  const ma=n=>i+1>=n?(sum[i+1]-sum[i+1-n])/n:null;
  out.push({...r,index:i,consecutive,ma5:ma(5),ma20:ma(20),ma50:ma(50),ma200:ma(200),
   atr:i>=20?(tr[i+1]-tr[i-19])/20:null,rsi2,momentum:i>=63?r.close/rows[i-63].close-1:null,
   priorHigh55:i>=55?Math.max(...rows.slice(i-55,i).map(q=>q.high)):null,
   priorLow20:i>=20?Math.min(...rows.slice(i-20,i).map(q=>q.low)):null,
   previousClose:p?.close,previousLow:p?.low,previousMA20:i>=20?(sum[i]-sum[i-20])/20:null});
 }
 return out;
}
function signal(f,market,id){
 const method=METHODS.find(q=>q.id===id);if(!method)throw Error('Unknown fixed method');
 if(!f||!market||f.date!==market.date||f.consecutive<200||!(f.atr>0)||
  !(market.ma200>0)||market.close<=market.ma200||2*f.atr/f.close>.08||f.close<=f.ma200)return null;
 const trend=f.ma50>f.ma200&&f.momentum>0;
 let pass=false,rank=f.momentum/(f.atr/f.close),target=null;
 if(id==='channel55')pass=trend&&f.close>f.priorHigh55;
 if(id==='pullback20'){
  pass=trend&&f.previousLow<=f.previousMA20+.35*f.atr&&f.close>f.ma20&&f.close>f.previousClose&&f.close>f.open;
  target=f.close+4*f.atr;
 }
 if(id==='rsi2'){pass=f.close<f.ma5&&f.rsi2<10;rank=-f.rsi2;}
 if(!pass)return null;
 return {side:'long',pattern:id,price:f.close,stop:f.close-2*f.atr,target,atr:f.atr,rank,
  holdBars:method.holdBars??Number.MAX_SAFE_INTEGER,reason:method.name,at:f.end};
}
function heldControl(f,market,id,p){
 if(!f||!market||f.date!==market.date)return {};
 let reason=null;
 if(market.close<=market.ma200)reason='SPY below SMA200';
 else if(id==='channel55'&&f.close<f.priorLow20)reason='20-session channel exit';
 else if(id==='pullback20'&&f.close<f.ma50)reason='SMA50 exit';
 else if(id==='rsi2'&&(f.close>f.ma5||f.close<=f.ma200))reason='mean reversion or trend exit';
 if(!reason&&p.bars>=p.holdBars)reason='holding limit at next open';
 const trail=id==='channel55'&&f.priorLow20<f.close&&f.priorLow20>(p.pendingStop?.price??p.stop)?f.priorLow20:null;
 return {reason,trail};
}
function queue(a,candidates){
 for(const q of [...candidates].sort(compare)){
  if(a.positions.some(p=>p.symbol===q.symbol)||a.pending.some(p=>p.symbol===q.symbol))continue;
  a.pending.push({...q,id:VERSION+':'+a.id+':'+q.symbol+':'+q.at,createdAt:q.at,notBefore:q.at+1,expires:q.at+5*DAY});
 }
 a.pending.sort(compare);
}
function execute(a,bars,reference,cfg){
 for(const p of a.positions)if(!bars[p.symbol])a.missingHeldSessions++;
 for(const [symbol,r] of Object.entries(bars))a.marks[symbol]=r.open;
 for(const p of [...a.positions]){
  const r=bars[p.symbol];if(!r)continue;
  if(p.pendingStop&&r.t>=p.pendingStop.notBefore){p.stop=p.pendingStop.price;delete p.pendingStop;}
  if(r.open<=p.stop)P.close(a,p,r.open,r.t,'stop gap',cfg,r.end,'open');
  else if(Number.isFinite(p.target)&&r.open>=p.target)P.close(a,p,p.target,r.t,'target gap',cfg,r.end,'open');
  else if(p.exitPending&&r.t>=p.exitNotBefore)P.close(a,p,r.open,r.t,p.exitPending,cfg,r.end,'open');
 }
 const keep=[];
 for(const order of a.pending){
  let reason;
  if(reference.t>order.expires)reason='expired';
  else if(reference.t<order.notBefore){keep.push(order);continue;}
  else if(!bars[order.symbol])reason='missing next open';
  else reason=P.enter(a,order,bars[order.symbol],{...cfg,trend:METHODS.find(m=>m.id===order.pattern).targetless},reference.end);
  if(reason)a.rejections[reason]=(a.rejections[reason]||0)+1;
 }
 a.pending=keep;
 for(const p of [...a.positions]){
  const r=bars[p.symbol];if(!r)continue;p.bars++;
  const stop=r.low<=p.stop,target=Number.isFinite(p.target)&&r.high>=p.target;
  if(stop||target)P.close(a,p,stop?p.stop:p.target,r.end,
   stop?(target?'stop before same-bar target':'stop'):'2R target',cfg,r.end,'bar');
 }
 for(const [symbol,r] of Object.entries(bars))a.marks[symbol]=r.close;
 const equity=P.equity(a);a.highWater=Math.max(a.highWater,equity);a.maxDrawdown=Math.max(a.maxDrawdown,1-equity/a.highWater);
 a.curve.push({date:reference.date,at:reference.end,equity,cash:a.cash,
  exposure:a.positions.reduce((s,p)=>s+p.qty*(a.marks[p.symbol]??p.entry),0),positions:a.positions.length,
  maxSectorPositions:Math.max(0,...Object.values(a.positions.reduce((s,p)=>{s[p.sector]=(s[p.sector]||0)+1;return s;},{})))});
}
function observe(a,featuresBySymbol,market,candidates){
 for(const p of a.positions){
  const f=featuresBySymbol[p.symbol],control=heldControl(f,market,a.method,p);if(!f)continue;
  if(control.reason&&!p.exitPending){p.exitPending=control.reason;p.exitNotBefore=f.end+1;}
  if(control.trail!==null&&control.trail!==undefined)p.pendingStop={price:control.trail,notBefore:f.end+1};
 }
 queue(a,candidates);
}
function labelRows(indexed,daily){
 return Object.fromEntries([20,63].map(h=>[h,daily.flatMap(r=>r.top3.map(symbol=>({...B.outcome(indexed,symbol,r.date,h),symbol,date:r.date})))]));
}
function summarizeLabels(labels,period){
 return Object.fromEntries(Object.entries(labels).map(([h,all])=>{
  const rows=[],excluded={};
  for(const r of all){
   if(period&&!inPeriod(r.date,period))continue;
   const why=r.excluded||((period&&r.endDate>period.end)?'crossesPeriodEnd':null);
   if(why)excluded[why]=(excluded[why]||0)+1;else rows.push(r);
  }
  const byDate=new Map();for(const r of rows){if(!byDate.has(r.date))byDate.set(r.date,[]);byDate.get(r.date).push(r);}
  return [h,{observations:rows.length,signalDates:byDate.size,excluded,meanNet:mean(rows.map(r=>r.net)),
   meanBenchmark:mean(rows.map(r=>r.benchmark)),meanExcess:mean(rows.map(r=>r.excess)),
   dateBalancedMeanExcess:mean([...byDate.values()].map(a=>mean(a.map(r=>r.excess)))),winRate:mean(rows.map(r=>Number(r.net>0)))}];
 }));
}
function frequency(daily,period){
 const rows=period?daily.filter(r=>inPeriod(r.date,period)):daily;
 return {sessions:rows.length,zeroDays:rows.filter(r=>r.candidates===0).length,
  zeroShare:mean(rows.map(r=>Number(r.candidates===0))),meanCandidates:mean(rows.map(r=>r.candidates)),
  signals:rows.reduce((s,r)=>s+r.candidates,0),top3Signals:rows.reduce((s,r)=>s+r.top3.length,0)};
}
function curvePeriod(curve,reference,period){
 const rows=curve.filter(r=>!r.phase),selected=rows.filter(r=>inPeriod(r.date,period));
 if(!selected.length)return null;
 const first=selected[0],last=selected.at(-1),index=rows.findIndex(r=>r.date===first.date);
 const previous=index?rows[index-1]:curve.find(r=>r.phase==='beforeFirstOpen');
 if(!previous)throw Error('Initial equity anchor required');
 const years=(last.at-previous.at)/(365.25*DAY);let high=previous.equity,dd=0;
 for(const r of selected){high=Math.max(high,r.equity);dd=Math.max(dd,1-r.equity/high);}
 return {start:first.date,end:last.date,sessions:selected.length,startEquity:previous.equity,
  endingEquity:last.equity,markReturn:last.equity/previous.equity-1,cagr:(last.equity/previous.equity)**(1/years)-1,
  maxDrawdown:dd,meanExposure:mean(selected.map(r=>r.exposure/r.equity)),
  basis:'continuous account, marked equity, positions carried; no extra boundary liquidation',
  previousEquityAt:previous.at};
}
function fullAccount(a,reference,cfg){
 const mark=P.equity(a),last=reference.at(-1),years=(last.end-reference[0].t)/(365.25*DAY);
 const liquidation=mark-a.positions.reduce((s,p)=>s+p.qty*a.marks[p.symbol]*(1-(1-cfg.slip)*(1-cfg.fee)),0);
 const report=P.report(a),symbolNet={};
 for(const t of a.trades)symbolNet[t.symbol]=(symbolNet[t.symbol]||0)+t.net;
 for(const p of a.positions)symbolNet[p.symbol]=(symbolNet[p.symbol]||0)+
  p.qty*(a.marks[p.symbol]*(1-cfg.slip)*(1-cfg.fee)-p.entry)-p.entryFee;
 const ranked=Object.entries(symbolNet).map(([symbol,net])=>({symbol,net})).sort((x,y)=>y.net-x.net||x.symbol.localeCompare(y.symbol));
 const positive=ranked.filter(q=>q.net>0).reduce((s,q)=>s+q.net,0),profit=liquidation-a.initial;
 const concentration={basis:'symbol P&L after fees, including terminal hypothetical liquidation; descriptive post-result audit',
  totalNetProfit:profit,topSymbols:ranked.slice(0,5),topSymbolShareOfNetProfit:profit>0&&ranked.length?ranked[0].net/profit:null,
  topSymbolShareOfPositiveSymbolPnL:positive>0?ranked[0].net/positive:null};
 return {initial:a.initial,markEquity:mark,liquidationEquivalentEquity:liquidation,
  liquidationEquivalentReturn:liquidation/a.initial-1,cagr:(liquidation/a.initial)**(1/years)-1,
  maxDrawdown:a.maxDrawdown,meanExposure:mean(a.curve.filter(r=>!r.phase).map(r=>r.exposure/r.equity)),
  entries:a.trades.length+a.positions.length,closedTrades:a.trades.length,openPositions:a.positions.length,
  winRate:report.winRate,profitFactor:report.profitFactor,fees:a.fees,slippage:a.slippage,
  missingHeldSessions:a.missingHeldSessions,rejections:a.rejections,concentration};
}
function summarize(a,daily,indexed,reference,cfg){
 const labels=labelRows(indexed,daily),periods={};
 for(const [id,p] of Object.entries(PERIODS))periods[id]={...curvePeriod(a.curve,reference,p),
  closedTrades:a.trades.filter(t=>inPeriod(new Date(t.exitAt).toISOString().slice(0,10),p)).length,
  frequency:frequency(daily,p),top3:summarizeLabels(labels,p)};
 const years=[...new Set(reference.map(r=>r.date.slice(0,4)))];
 return {full:fullAccount(a,reference,cfg),frequency:frequency(daily),top3:summarizeLabels(labels),periods,
  annual:Object.fromEntries(years.map(y=>[y,curvePeriod(a.curve,reference,{start:y+'-01-01',end:y+'-12-31'})]))};
}
function run(data,{start=PERIODS.early.start,onProgress=()=>{}}={}){
 const indexed=B.indexData(data),reference=indexed.SPY.rows.filter(r=>r.date>=start),calendar=indexed.SPY.byDate;
 if(!reference.length)throw Error('No evaluation sessions');
 const computed={};for(const [s,source] of Object.entries(indexed))computed[s]=features(source.rows,calendar);
 const states={};
 for(const m of METHODS)for(const stress of [false,true]){
  const id=m.id+(stress?'_stress':''),account=B.newAccount(reference[0]);
  Object.assign(account,{id,method:m.id,stress});states[id]={account,daily:[],cfg:cfgFor(stress)};
 }
 for(let di=0;di<reference.length;di++){
  const ref=reference[di],bars={},today={};
  for(const [s,source] of Object.entries(indexed)){
   const i=source.byDate.get(ref.date);if(i!==undefined){bars[s]=source.rows[i];today[s]=computed[s][i];}
  }
  for(const state of Object.values(states))execute(state.account,bars,ref,state.cfg);
  for(const m of METHODS){
   const candidates=[];
   for(const [symbol,f] of Object.entries(today)){
    const q=signal(f,today.SPY,m.id);if(q)candidates.push({...q,symbol,sector:indexed[symbol].sector});
   }
   candidates.sort(compare);
   const daily={date:ref.date,candidates:candidates.length,top3:candidates.slice(0,3).map(q=>q.symbol),
    priceRegime:today.SPY.close>today.SPY.ma200?'above200':'below200'};
   for(const suffix of ['','_stress']){
    const s=states[m.id+suffix];s.daily.push(daily);observe(s.account,today,today.SPY,candidates);
   }
  }
  if(di%250===0||di===reference.length-1)onProgress({completed:di+1,sessions:reference.length,date:ref.date});
 }
 const methods={};
 for(const [id,s] of Object.entries(states))methods[id]={id,name:METHODS.find(m=>m.id===s.account.method).name,
  stress:s.account.stress,cost:s.cfg,...summarize(s.account,s.daily,indexed,reference,s.cfg),latest:s.daily.at(-1)};
 const ordered=METHODS.map(m=>methods[m.id]).sort((a,b)=>b.periods.early.cagr-a.periods.early.cagr||a.id.localeCompare(b.id));
 return {version:VERSION,start:reference[0].date,end:reference.at(-1).date,symbols:Object.keys(indexed).length,
  methods,selection:{rule:'highest early marked CAGR among the three normal-cost alternatives; ties by id',
   selected:ordered[0].id,earlyCAGR:ordered[0].periods.early.cagr,recentCAGR:ordered[0].periods.recent?.cagr??null,
   automaticPromotion:false},details:states};
}
function parseCSV(text){
 const records=[];let row=[],field='',quoted=false;
 for(let i=0;i<text.length;i++){
  const c=text[i];
  if(quoted){if(c==='"'&&text[i+1]==='"'){field+='"';i++;}else if(c==='"')quoted=false;else field+=c;}
  else if(c==='"')quoted=true;
  else if(c===','){row.push(field);field='';}
  else if(c==='\n'){row.push(field.replace(/\r$/,''));if(row.some(x=>x!==''))records.push(row);row=[];field='';}
  else field+=c;
 }
 if(quoted)throw Error('Unclosed CSV quote');
 if(row.length||field){row.push(field);records.push(row);}
 const header=records.shift();return records.map(r=>Object.fromEntries(header.map((k,i)=>[k,r[i]??''])));
}
function csv(rows,columns){
 return columns.join(',')+'\n'+rows.map(r=>columns.map(k=>{const x=String(r[k]??'');
  return /[,"\n]/.test(x)?'"'+x.replaceAll('"','""')+'"':x;}).join(',')).join('\n')+'\n';
}
function baseline(directory,indexed,reference,inputSHA){
 const prior=JSON.parse(fs.readFileSync(path.join(directory,'results.json'))),out={};
 if(prior.input.sha256!==inputSHA||prior.start!==reference[0].date||prior.end!==reference.at(-1).date)throw Error('Baseline input/date mismatch');
 for(const [p,h] of Object.entries(prior.sourceHashes))if(sha(fs.readFileSync(path.join(ROOT,p)))!==h)throw Error('Frozen baseline source changed: '+p);
 for(const status of ['stable','watch']){
  const read=suffix=>parseCSV(fs.readFileSync(path.join(directory,status+'-'+suffix+'.csv'),'utf8'));
  const daily=read('daily').map(r=>({date:r.date,candidates:Number(r.buy),top3:r.top3?r.top3.split('|'):[]}));
  const curve=read('curve').map(r=>({...r,at:Number(r.at),equity:Number(r.equity),cash:Number(r.cash),exposure:Number(r.exposure)}));
  if(daily.length!==reference.length||daily.some((r,i)=>r.date!==reference[i].date))throw Error('Baseline calendar mismatch');
  const labels=labelRows(indexed,daily),top3=summarizeLabels(labels);
  for(const h of [20,63])if(top3[h].observations!==prior.scenarios[status].top3Outcomes[h].observations||
   Math.abs(top3[h].meanNet-prior.scenarios[status].top3Outcomes[h].meanNet)>1e-12)throw Error('Frozen TOP3 outcome mismatch');
  const periods={};for(const [id,p] of Object.entries(PERIODS))periods[id]={...curvePeriod(curve,reference,p),
   frequency:frequency(daily,p),top3:summarizeLabels(labels,p)};
  out['current_'+status]={id:'current_'+status,name:'현재 규칙 '+status+' 가정',full:prior.scenarios[status].portfolio,
   frequency:frequency(daily),top3,periods,annual:prior.scenarios[status].portfolio.annual,
   assumption:'fixed synthetic '+status+' credit, not historical observed macro',latest:daily.at(-1)};
 }
 return out;
}
function benchmark(reference,cfg){
 const qty=10000/(reference[0].open*(1+cfg.slip)*(1+cfg.fee)),a=B.newAccount(reference[0]);
 for(const r of reference)a.curve.push({date:r.date,at:r.end,equity:qty*r.close,cash:0,exposure:qty*r.close});
 const end=qty*reference.at(-1).close,net=end*(1-cfg.slip)*(1-cfg.fee),years=(reference.at(-1).end-reference[0].t)/(365.25*DAY);
 return {id:'SPY',name:'SPY 가격 보유',basis:'price-only, no dividends, fractional shares, same dates and normal costs',
  full:{initial:10000,markEquity:end,liquidationEquivalentEquity:net,liquidationEquivalentReturn:net/10000-1,
   cagr:(net/10000)**(1/years)-1,maxDrawdown:curvePeriod(a.curve,reference,{start:reference[0].date,end:reference.at(-1).date}).maxDrawdown,
   meanExposure:1},periods:Object.fromEntries(Object.entries(PERIODS).map(([id,p])=>[id,curvePeriod(a.curve,reference,p)])),curve:a.curve};
}
function main(){
 const arg=k=>{const i=process.argv.indexOf(k);return i<0?undefined:process.argv[i+1];};
 const input=arg('--input')||path.join(ROOT,'research/history/entry-backtest-2026-10-04/prices.json.gz');
 const directory=arg('--output')||path.join(ROOT,'research/entry-strategy-comparison/2026-10-04');
 const raw=zlib.gunzipSync(fs.readFileSync(input)),inputSHA=sha(raw);
 if(inputSHA!==INPUT_SHA)throw Error('Different price vintage; create a separately versioned comparison');
 const data=JSON.parse(raw),indexed=B.indexData(data),reference=indexed.SPY.rows.filter(r=>r.date>=PERIODS.early.start);
 const baselineDir=path.join(ROOT,'research/entry-backtest/2026-10-04');
 const controls=baseline(baselineDir,indexed,reference,inputSHA);
 const result=run(data,{onProgress:p=>process.stderr.write(JSON.stringify(p)+'\n')}),states=result.details;delete result.details;
 const spy=benchmark(reference,cfgFor(false));
 result.controls=controls;result.benchmark={...spy};delete result.benchmark.curve;
 result.input={path:path.relative(ROOT,input),sha256:inputSHA,cutoff:data.cutoff,basis:data.basis,
  universeSHA256:data.universeSHA256,homeUniverseSHA256:data.homeUniverseSHA256};
 result.periodDefinition=PERIODS;
 const baseFiles=['results.json',...['stable','watch'].flatMap(s=>['curve.csv','daily.csv','trades.csv','open.json'].map(f=>s+'-'+f))]
  .map(p=>'research/entry-backtest/2026-10-04/'+p);
 const sourceFiles=['scripts/entry_strategy_comparison.cjs','scripts/test_entry_strategy_comparison.cjs',
  'scripts/render_entry_strategy_comparison.py','research/entry-strategy-comparison/2026-10-04/PROTOCOL.md',
  'scripts/backtest_entry_rules.cjs','scripts/entry_study.cjs',...['technical-guide','paper-engine','simulation-signals','perp-engine'].map(s=>'scripts/entry-study-v1/'+s+'.cjs'),...baseFiles];
 result.sourceHashes=Object.fromEntries(sourceFiles.map(p=>[p,sha(fs.readFileSync(path.join(ROOT,p)))]));
 fs.mkdirSync(directory,{recursive:true});
 fs.writeFileSync(path.join(directory,'results.json'),JSON.stringify(result,null,2)+'\n');
 for(const [id,s] of Object.entries(states)){
  fs.writeFileSync(path.join(directory,id+'-curve.csv'),csv(s.account.curve,['date','at','phase','equity','cash','exposure','positions','maxSectorPositions']));
  fs.writeFileSync(path.join(directory,id+'-trades.csv'),csv(s.account.trades,['symbol','sector','pattern','signalAt','entryAt','entry','qty','stop','target','exitAt','exit','exitReason','net','entryFee','exitFee','bars']));
  fs.writeFileSync(path.join(directory,id+'-open.json'),JSON.stringify(s.account.positions.map(p=>({...p,mark:s.account.marks[p.symbol]})),null,2)+'\n');
  if(!s.account.stress)fs.writeFileSync(path.join(directory,id+'-daily.csv'),csv(s.daily.map(r=>({...r,top3:r.top3.join('|')})),['date','candidates','top3','priceRegime']));
 }
 fs.writeFileSync(path.join(directory,'SPY-curve.csv'),csv(spy.curve,['date','at','phase','equity','cash','exposure']));
 process.stdout.write(JSON.stringify({selection:result.selection,methods:Object.fromEntries(Object.entries(result.methods).map(([id,s])=>[id,
  {cagr:s.full.cagr,drawdown:s.full.maxDrawdown,early:s.periods.early.cagr,recent:s.periods.recent.cagr,zero:s.frequency.zeroShare,closed:s.full.closedTrades}]))})+'\n');
}
module.exports={VERSION,METHODS,PERIODS,cfgFor,features,signal,heldControl,queue,execute,observe,run,parseCSV,csv,
 frequency,summarizeLabels,curvePeriod,baseline,benchmark,compare};
if(require.main===module)main();
