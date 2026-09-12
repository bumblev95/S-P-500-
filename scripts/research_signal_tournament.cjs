'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const M=require('./signal_tournament.cjs'),P=require('./paper_engine.cjs'),X=require('./research_exit_methods.cjs');
const ROOT=path.resolve(__dirname,'..'),DAY=86400000,FOLDER=path.join(ROOT,'simulation/signal-tournament');
const digest=x=>crypto.createHash('sha256').update(x).digest('hex');
const compact=r=>{const {curve,riskCurve,closed,...rest}=r;return rest;};
function riskCurve(curve){const days=new Map();for(const v of curve){const d=Math.floor(v.at/DAY),g=days.get(d)||{min:v,max:v,last:v};if(v.equity<g.min.equity)g.min=v;if(v.equity>g.max.equity)g.max=v;g.last=v;days.set(d,g);}return [...days.values()].flatMap(g=>[g.min,g.max,g.last].sort((a,b)=>a.at-b.at)).filter((v,i,a)=>!i||v.at!==a[i-1].at).map(v=>({at:v.at,equity:v.equity}));}
function sliced(market,start,end){return {...market,crypto:Object.fromEntries(Object.entries(market.crypto).map(([s,v])=>[s,{...v,frames:{'15m':v.frames['15m'].filter(r=>r.t>=start&&r.end<=end)},funding:v.funding}]))};}
function evaluate(market,maps,scores,method,start,end,stress=false,cap=1){
 const a=P.create('crypto',start,stress?'selectorTargetsStress':'selectorTargets'),cfg=P.config(a),old=cfg.maxPositions;cfg.maxPositions=cap;
 try{
  const provider=(s,rows)=>{const at=rows.at(-1).end;return M.apply(method,maps[s]?.get(at),scores.get(s+':'+at));};
  const state=P.run(a,market,{mode:'replay',startAt:start,now:end+1,provider});
  for(const p of [...state.positions])P.close(state,p,state.marks[p.symbol],state.marketAsOf,'평가 종료',cfg,end,'close');
  const r=P.report(state);r.maxDrawdown=Math.max(r.maxDrawdown,1-r.equity/r.highWater);if(r.curve.length)r.curve.at(-1).equity=r.equity;
  if(Math.abs(r.equity-10000-r.trades.reduce((s,t)=>s+t.net,0))>1e-5)throw Error('Account reconciliation failed');
  if(r.trades.some(t=>t.entryAt<=t.signalAt))throw Error('Signal chronology failed');
  const events=r.trades.flatMap(t=>[{at:t.entryAt,n:1},{at:t.exitAt,n:-1}]).sort((a,b)=>a.at-b.at||a.n-b.n);let held=0,maxHeld=0;for(const e of events){held+=e.n;maxHeld=Math.max(maxHeld,held);}if(maxHeld>cap)throw Error('Position cap exceeded');
  const daily=new Map();for(const v of r.curve)daily.set(Math.floor(v.at/DAY),{at:v.at,equity:v.equity});
  const bySymbol=Object.fromEntries(['BTC','ETH','SOL'].map(s=>{const ts=r.trades.filter(t=>t.symbol===s);return [s,{trades:ts.length,net:ts.reduce((x,t)=>x+t.net,0)}];}));
  return {method:method.id,start,end,cap,equity:r.equity,return:r.return,maxDrawdown:r.maxDrawdown,...X.metrics(r.curve,r.trades,start,end,r.equity,r.maxDrawdown),trades:r.trades.length,winRate:r.winRate,profitFactor:r.profitFactor,fees:r.fees,funding:r.funding,slippage:r.slippage,estimatedFundingHours:r.estimatedFundingHours,maxHeld,bySymbol,warnings:r.warnings,curve:[...daily.values()],riskCurve:riskCurve(r.curve),closed:r.trades.map(t=>({symbol:t.symbol,side:t.side,signalAt:t.signalAt,entryAt:t.entryAt,exitAt:t.exitAt,net:t.net,netR:t.net/t.riskBudget,reason:t.exitReason}))};
 }finally{cfg.maxPositions=old;}
}
function eligible(r){return r.trades>=20&&r.return>0&&r.stress.return>0&&r.maxDrawdown<=.25&&(r.expectancyR||0)>0;}
function choose(rows){return rows.filter(eligible).sort((a,b)=>score(b)-score(a)||a.method.localeCompare(b.method))[0]?.method||'cash';}
function score(r){return (r.sharpe||0)-2*r.maxDrawdown;}
function stitch(rows,start,end){
 let scale=1,high=10000,dd=0;const curve=[],closed=[];
 for(const r of rows){for(const p of r.riskCurve){const equity=p.equity*scale;curve.push({at:p.at,equity});high=Math.max(high,equity);dd=Math.max(dd,1-equity/high);}for(const t of r.closed)closed.push({...t,net:t.net*scale});scale*=r.equity/10000;}
 const equity=10000*scale,daily=new Map();for(const p of curve)daily.set(Math.floor(p.at/DAY),p);
 return {equity,return:scale-1,maxDrawdown:dd,...X.metrics(curve,closed,start,end,equity,dd),trades:closed.length,winRate:closed.length?closed.filter(t=>t.net>0).length/closed.length:null,curve:[...daily.values()]};
}
function cash(start,end){const curve=[];for(let t=start;t<=end;t+=DAY)curve.push({at:t,equity:10000});return {equity:10000,riskCurve:curve,closed:[]};}
function run(){
 const input=process.env.SIGNAL_RESEARCH_DATA;if(!input)throw Error('Set SIGNAL_RESEARCH_DATA to checksum-verified repaired research directory');
 const marketBytes=fs.readFileSync(path.join(input,'futures-market.json')),market=JSON.parse(marketBytes),manifest=JSON.parse(fs.readFileSync(path.join(input,'futures-manifest.json')));
 if(manifest.errors.length||Object.values(manifest.coverage).some(v=>v.missingBars||v.invalidRows))throw Error('Incomplete input');
 const scoreBytes=fs.readFileSync(path.join(input,'futures-test-scores.json')),scores=new Map(JSON.parse(scoreBytes).map(r=>[r.symbol+':'+r.at,r.boost]));
 const start=Date.UTC(2022,0,1),end=Math.min(...Object.values(manifest.coverage).map(v=>v.end));
 const sourceHashes=Object.fromEntries(['signal_tournament.cjs','research_signal_tournament.cjs','paper_engine.cjs','trend_methods.cjs','public_bot_methods.cjs','research_exit_methods.cjs'].map(f=>[f,digest(fs.readFileSync(path.join(__dirname,f)))]));
 const protocol={version:'public-signal-tournament-v1',createdAt:new Date().toISOString(),methods:M.METHODS,start,end,trainingYear:2021,marketHash:digest(marketBytes),scoreHash:digest(scoreBytes),sourceHashes,decision:'32 frozen recipes; shared 1-position engine; annual prior-year selection; no automatic account replacement',selection:'Prior calendar year: >=20 exits, positive net and double-cost return, MDD<=25%, positive mean netR. Max daily Sharpe minus 2*MDD; ties alphabetical; no eligible candidate means cash.',costs:'Each side 0.045% fee + 0.02% slippage; recorded funding. Stress doubles fee/slippage only. BTC5x ETH/SOL3x; 1% initial risk budget; existing drawdown and daily loss controls.',endings:'Annual experiments force-close at year end; continuous fixed experiments close only at final end. Selection stitches annual flat starts.',knn:'Independent Lorentzian-distance kNN adaptation, not a port of jdehorty. 5 bounded features, last2000 bars sampled every4, 8 neighbors,4-bar net-direction target with0.13% deadband. Each target ends >=1 bar before decision. Min100 known samples; vote>=0.25.',limitations:['Historical periods and current symbols have already been examined. Chronological selection is not pristine out-of-sample proof.','Futures data are 2020–2026, not 15 years; fixed comparisons start2022. SOL data begin2020-09.','Original TradingView/Freqtrade software was not executed. OHLC signals were independently adapted, and common exits/portfolio sizing replace original bots.','No Heikin Ashi execution, averaging down, grid or martingale. The current production paper accounts are unchanged.','The 2026 boosting model is not applied to earlier years. Stored prior-year-trained yearly OOS scores from the previous research are used.','Reusing a model trained for momentum trades to filter unrelated bots would change its meaning; boosting is used only with its original momentum breakout entry.']};
 fs.mkdirSync(FOLDER,{recursive:true});fs.writeFileSync(path.join(FOLDER,'plan.json'),JSON.stringify(protocol,null,2));
 const maps=Object.fromEntries(Object.entries(market.crypto).map(([s,v])=>{const m=M.prepare(v.frames['15m']);console.log('Prepared',s,m.size);return [s,m];}));
 const fixed=[],yearly=[],details=new Map();
 const full=sliced(market,start,end);
 for(const method of M.METHODS){
  const r=evaluate(full,maps,scores,method,start,end),stress=evaluate(full,maps,scores,method,start,end,true);
  fixed.push({...compact(r),stress:compact(stress),curve:r.curve});
  console.log(JSON.stringify({phase:'fixed',method:method.id,return:r.return,dd:r.maxDrawdown,trades:r.trades,stress:stress.return}));
  fs.writeFileSync(path.join(FOLDER,'checkpoint.json'),JSON.stringify({protocol,fixed,yearly}));
 }
 for(let year=2021;year<=new Date(end).getUTCFullYear();year++){
  const from=Date.UTC(year,0,1),to=Math.min(end,Date.UTC(year+1,0,1)-1),subset=sliced(market,from,to),results=[];
  for(const method of M.METHODS){
   const r=evaluate(subset,maps,scores,method,from,to),stress=evaluate(subset,maps,scores,method,from,to,true);r.stress=compact(stress);results.push(compact(r));details.set(year+':'+method.id,r);
  }
  yearly.push({year,start:from,end:to,results});console.log('Completed year',year,'best prior-year score',choose(results));fs.writeFileSync(path.join(FOLDER,'checkpoint.json'),JSON.stringify({protocol,fixed,yearly}));
 }
 const selected=[],selectedRows=[],selectedStress=[];
 for(const yr of yearly.filter(r=>r.year>=2022)){
  const before=yearly.find(r=>r.year===yr.year-1),id=choose(before.results);selected.push({year:yr.year,validationYear:before.year,method:id,validationEnd:before.end});
  selectedRows.push(id==='cash'?cash(yr.start,yr.end):details.get(yr.year+':'+id));
  selectedStress.push(id==='cash'?cash(yr.start,yr.end):evaluate(sliced(market,yr.start,yr.end),maps,scores,M.METHODS.find(m=>m.id===id),yr.start,yr.end,true));
 }
 const walkForward={...stitch(selectedRows,start,end),selected,stress:stitch(selectedStress,start,end)};
 // Display descriptive, same-start controls for the old 3-position default and the current ML baseline.
 const reference3=evaluate(full,maps,scores,M.METHODS.find(m=>m.id==='momentum_target6'),start,end,false,3);
 const associations=[];
 for(const family of Object.keys({momentum:1,ut:1,supertrend:1,squeeze:1,channel:1,macdbb:1}))for(const filter of ['ema','adx']){
  const a=fixed.find(r=>r.method===family+'_none'),b=fixed.find(r=>r.method===family+'_'+filter);associations.push({base:a.method,combined:b.method,returnDelta:b.return-a.return,drawdownDelta:b.maxDrawdown-a.maxDrawdown,sharpeDelta:(b.sharpe||0)-(a.sharpe||0)});
 }
 for(const r of fixed){const years=yearly.filter(y=>y.year>=2022).map(y=>y.results.find(v=>v.method===r.method));r.positiveYears=years.filter(y=>y.return>0).length;r.worstYear=Math.min(...years.map(y=>y.return));r.researchScreen=r.return>0&&r.stress.return>0&&r.maxDrawdown<=.20&&r.trades>=100&&r.positiveYears>=4;}
 const correlation=(a,b)=>{const toR=c=>new Map(c.slice(1).map((p,i)=>[Math.floor(p.at/DAY),p.equity/c[i].equity-1])),x=toR(a),y=toR(b),pairs=[...x].filter(([d])=>y.has(d)).map(([d,v])=>[v,y.get(d)]),mean=k=>pairs.reduce((s,p)=>s+p[k],0)/pairs.length,mx=mean(0),my=mean(1);let cov=0,vx=0,vy=0;for(const [v,w]of pairs){cov+=(v-mx)*(w-my);vx+=(v-mx)**2;vy+=(w-my)**2;}return vx*vy>0?cov/Math.sqrt(vx*vy):null;};
 const families=['momentum_none','ut_none','supertrend_none','squeeze_none','channel_none','macdbb_none','rsi_none','knn_none'];
 const correlations=families.flatMap((a,i)=>families.slice(i+1).map(b=>({a,b,correlation:correlation(fixed.find(r=>r.method===a).curve,fixed.find(r=>r.method===b).curve)})));
 for(const r of fixed)r.curve=r.curve.filter((v,i,a)=>i%7===0||i===a.length-1);
 walkForward.curve=walkForward.curve.filter((v,i,a)=>i%7===0||i===a.length-1);walkForward.stress.curve=walkForward.stress.curve.filter((v,i,a)=>i%7===0||i===a.length-1);
 const report={...protocol,generatedAt:new Date().toISOString(),coverage:manifest.coverage,evaluations:fixed.length*2+yearly.length*M.METHODS.length*2+selectedStress.filter(r=>r.method).length+1,fixed,yearly,walkForward,reference3:compact(reference3),associations,correlations};
 fs.writeFileSync(path.join(FOLDER,'latest.json'),JSON.stringify(report));fs.unlinkSync(path.join(FOLDER,'checkpoint.json'));
 console.log('FINISHED',JSON.stringify({evaluations:report.evaluations,walkForward:{return:walkForward.return,dd:walkForward.maxDrawdown,selected},top:[...fixed].sort((a,b)=>b.return-a.return).slice(0,5).map(r=>({method:r.method,return:r.return,dd:r.maxDrawdown}))}));
}
if(require.main===module)run();module.exports={evaluate,choose,eligible,score,stitch,sliced};
