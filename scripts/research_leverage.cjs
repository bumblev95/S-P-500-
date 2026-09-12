'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const M=require('./leverage_methods.cjs'),E=require('./leverage_engine.cjs');
const FOLDER=path.resolve(__dirname,'../simulation/leverage-lab'),hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const compact=r=>{const {curve,closed,...rest}=r;return rest;};
const key=r=>r.method+':'+r.policy+':'+r.leverage;
function choose(rows){return [...rows].filter(r=>r.trades>=20&&r.return>0&&r.stress.return>0&&r.maxDrawdown<=.4).sort((a,b)=>(Math.log1p(b.return)-b.maxDrawdown)-(Math.log1p(a.return)-a.maxDrawdown)||key(a).localeCompare(key(b)))[0]||null;}
function stitch(rows,start,end){
 let high=10000,dd=0;const curve=[],closed=[];
 for(const r of rows){
  const annualMin=r.minEquity??10000,annualHigh=r.peakEquity??10000;
  dd=Math.max(dd,r.maxDrawdown,1-annualMin/high);
  curve.push(...r.curve);closed.push(...r.closed);high=Math.max(high,annualHigh);
 }
 return {...E.metrics(curve,closed,start,end,dd),curve};
}
function run(){
 const input=process.env.LEVERAGE_RESEARCH_DATA;if(!input)throw Error('Set LEVERAGE_RESEARCH_DATA');
 const bytes=fs.readFileSync(path.join(input,'futures-market.json')),market=JSON.parse(bytes),manifest=JSON.parse(fs.readFileSync(path.join(input,'futures-manifest.json'))),scoreBytes=fs.readFileSync(path.join(input,'futures-test-scores.json'));
 if(manifest.errors.length||Object.values(manifest.coverage).some(c=>c.missingBars||c.invalidRows))throw Error('Input coverage failed');
 const scores=new Map(JSON.parse(scoreBytes).map(r=>[r.symbol+':'+r.at,r.boost])),start=Date.UTC(2022,0,1),end=Math.min(...Object.values(manifest.coverage).map(c=>c.end));
 const combinations=M.METHODS.flatMap(m=>M.POLICIES.flatMap(p=>[5,10].map(leverage=>({method:m.id,policy:p.id,leverage}))));
 const protocol={version:'leverage-allocation-v1',createdAt:new Date().toISOString(),start,end,methods:M.METHODS,policies:M.POLICIES,combinations,marketHash:hash(bytes),scoreHash:hash(scoreBytes),sourceHashes:Object.fromEntries(['leverage_methods.cjs','leverage_engine.cjs','research_leverage.cjs','trend_methods.cjs'].map(f=>[f,hash(fs.readFileSync(path.join(__dirname,f)))])),
  allocation:'One concurrent position, $10,000 initial capital, isolated margin. Leverage5/10. Risk1/2/4% targets include initial stop/fee/slippage risk and cap margin at90%; fixed margin25/50/90% targets that equity fraction irrespective of stop risk. Every entry is capped at0.5% of the smaller of signal-bar volume and prior32-bar mean volume; target allocation can be underfilled. No leverage averaging, martingale, drawdown sizing, daily stop or loss-streak cooldown. Stop/gap losses can exceed the planned risk. If flat equity drops below1% of initial capital, remain in cash.',
  fills:'Signals from completed bars only; next15m open with adverse slippage. Reject wrong-side stops, open gaps over half initial stop distance, or stop beyond estimated liquidation. One candidate at a time, descending signal rank then alphabetical symbol. At same bar stop/target crossing, stop first; stop/liq crossing follows first reachable price threshold. Partial sells50% of remaining initial position once. Break-even/trail updated only for next bar. Final positions force-closed.',
  costs:'Per side fee0.045% + slippage0.02%. Cost stress doubles both. Actual historical funding rates, timestamps rounded to settlement hour; opening after settlement pays next settlement. Missing settlement intervals charged0.01% notional per missing payment, never credited. Funding debits isolated margin.',
  liquidation:'Approximation using traded OHLC as mark proxy, flat maintenance2.5%, entire remaining isolated margin forfeited at liquidation, no top-up. Separate liquidation stress uses5% maintenance and adverse0.5% mark deviation with ordinary fees. These are declared research assumptions, not historical Binance liquidation tiers or real matching-engine fills.',
  selection:'For each year2022–2026, use previous calendar year only: >=20 exits, positive ordinary and double-cost net return, MDD<=40%. Choose maximum log(1+return)-MDD; tie by method:policy:leverage; no eligible means cash. Each annual segment starts flat. Boost scores begin2022 so cannot win2021 selection.',
  shortlist:'Descriptive full-period screen: >=100 exits, ordinary and double-cost return positive, MDD<=40%, four of five annual periods positive. A screen pass is not independent validation.',
  limitations:['Data and strategy ideas have already been studied. This is exploratory comparison, not a pristine holdout or independent proof of an optimal strategy.','Same BTC/ETH/SOL universe controls this sizing comparison. No broader equity/crypto leader scan, point-in-time delistings or news-based EP are tested.','Qullamaggie-inspired rules are crypto adaptations, not a replication of his equity selection, discretionary pattern reading, opening session or claimed returns.','Real futures comparison covers2022-01 through2026-08, using2020 onward history for features. It is not a15-year futures test.2026 is partial.','No order-book capacity model, historical maintenance tiers, insurance fund mechanics or exchange outages. High-exposure compounded results may substantially overstate executable dollar returns.','Boosting uses existing year-specific past-trained scores only for the entry it was trained on. No current model is retroactively applied.','5/10x is position leverage. Account notional exposure equals margin fraction times leverage; risk-based policies often deploy much less.'],
  sources:[{title:'Qullamaggie original setups',url:'https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/'},{title:'Official Binance public market archives',url:'https://github.com/binance/binance-public-data'},{title:'Margin and isolated collateral mechanics',url:'https://hyperliquid.gitbook.io/hyperliquid-docs/trading/margining'},{title:'Mark-based liquidation mechanics',url:'https://hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations'}]};
 fs.mkdirSync(FOLDER,{recursive:true});fs.writeFileSync(path.join(FOLDER,'plan.json'),JSON.stringify(protocol,null,2));
 const base=Math.min(...Object.values(market.crypto).map(v=>v.frames['15m'][0].t)),data={start:base,symbols:{}};
 for(const [s,v] of Object.entries(market.crypto)){const rows=v.frames['15m'];data.symbols[s]={rows,offset:(rows[0].t-base)/M.STEP,prepared:M.prepare(rows,scores,s),funding:E.fundingGrid(rows,v.funding)};console.log('Prepared',s,Object.fromEntries(Object.entries(data.symbols[s].prepared.events).map(([k,v])=>[k,[...v.values()].filter(q=>q.side).length])));}
 const evaluate=(c,from,to,options={})=>E.evaluate(data,M.METHODS.find(m=>m.id===c.method),M.POLICIES.find(p=>p.id===c.policy),c.leverage,from,to,options);
 const fixed=[],yearly=[];let evaluations=0;
 for(const c of combinations){const r=evaluate(c,start,end),stress=evaluate(c,start,end,{costStress:true}),liquidationStress=evaluate(c,start,end,{maintenance:.05,markBuffer:.005});evaluations+=3;fixed.push({...compact(r),stress:compact(stress),liquidationStress:compact(liquidationStress),curve:r.curve.filter((p,i,a)=>i%7===0||i===a.length-1)});console.log('Fixed',key(c),JSON.stringify({return:r.return,dd:r.maxDrawdown,trades:r.trades,stress:stress.return,liq:r.liquidations}));}
 for(let year=2021;year<=2026;year++){
  const from=Date.UTC(year,0,1),to=Math.min(end,Date.UTC(year+1,0,1)-1),results=[];
  for(const c of combinations){const r=evaluate(c,from,to),stress=evaluate(c,from,to,{costStress:true});evaluations+=2;results.push({...compact(r),stress:compact(stress)});}
  yearly.push({year,start:from,end:to,results});console.log('Year',year,'next choice',key(choose(results)||{}));
 }
 const selected=[],chosen=[],chosenStress=[];let balance=10000,stressBalance=10000;
 for(const yr of yearly.filter(y=>y.year>=2022)){
  const prev=yearly.find(y=>y.year===yr.year-1),c=choose(prev.results);selected.push({year:yr.year,validationYear:prev.year,validationEnd:prev.end,combination:c?key(c):'cash'});
  if(c){chosen.push(evaluate(c,yr.start,yr.end,{initialEquity:balance}));chosenStress.push(evaluate(c,yr.start,yr.end,{costStress:true,initialEquity:stressBalance}));evaluations+=2;}
  else{const cash=equity=>{const curve=[];for(let t=yr.start+M.DAY-1;t<=yr.end;t+=M.DAY)curve.push({at:t,equity});return {equity,minEquity:equity,peakEquity:equity,maxDrawdown:0,curve,closed:[]};};chosen.push(cash(balance));chosenStress.push(cash(stressBalance));}
  balance=chosen.at(-1).equity;stressBalance=chosenStress.at(-1).equity;
  Object.assign(selected.at(-1),{return:chosen.at(-1).return??0,equity:balance,stressReturn:chosenStress.at(-1).return??0});
 }
 for(const r of fixed){const ys=yearly.filter(y=>y.year>=2022).map(y=>y.results.find(q=>key(q)===key(r)));r.positiveYears=ys.filter(y=>y.return>0).length;r.worstYear=Math.min(...ys.map(y=>y.return));r.researchScreen=r.trades>=100&&r.return>0&&r.stress.return>0&&r.maxDrawdown<=.4&&r.positiveYears>=4;}
 const wf=stitch(chosen,start,end),wfStress=stitch(chosenStress,start,end);
 const report={...protocol,generatedAt:new Date().toISOString(),coverage:manifest.coverage,evaluations,fixed,yearly,walkForward:{...wf,curve:wf.curve.filter((p,i,a)=>i%7===0||i===a.length-1),selected,stress:{...wfStress,curve:wfStress.curve.filter((p,i,a)=>i%7===0||i===a.length-1)}}};
 fs.writeFileSync(path.join(FOLDER,'latest.json'),JSON.stringify(report));fs.writeFileSync(path.join(FOLDER,'input-manifest.json'),JSON.stringify({marketHash:protocol.marketHash,scoreHash:protocol.scoreHash,coverage:manifest.coverage,errors:manifest.errors},null,2));
 const top=[...fixed].sort((a,b)=>b.return-a.return).slice(0,8).map(r=>({key:key(r),return:r.return,dd:r.maxDrawdown,stress:r.stress.return,screen:r.researchScreen}));console.log('FINISHED',JSON.stringify({evaluations,top,shortlist:fixed.filter(r=>r.researchScreen).length,walkForward:{return:wf.return,dd:wf.maxDrawdown,stress:wfStress.return,selected}}));
}
if(require.main===module)run();module.exports={choose,stitch,key};
