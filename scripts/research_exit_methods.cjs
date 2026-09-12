'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const P=require('./paper_engine.cjs'),T=require('./trend_methods.cjs'),X=require('./exit_methods.cjs');
const {sliceMarket}=require('./research_momentum_cpd.cjs');
const ROOT=path.resolve(__dirname,'..'),DAY=86400000,VERSION='momentum14-exit-walkforward-v1';
const hash=f=>crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');

function metrics(curve,trades,start,end,equity,maxDrawdown){
 const daily=new Map();for(const v of curve)daily.set(Math.floor(v.at/DAY),v.equity);
 const values=[10000,...[...daily.entries()].sort((a,b)=>a[0]-b[0]).map(v=>v[1])],returns=[];
 for(let i=1;i<values.length;i++)if(values[i-1]>0)returns.push(values[i]/values[i-1]-1);
 const mean=returns.length?returns.reduce((s,v)=>s+v,0)/returns.length:0;
 const variance=returns.length>1?returns.reduce((s,v)=>s+(v-mean)**2,0)/(returns.length-1):0;
 const sharpe=variance>0?mean/Math.sqrt(variance)*Math.sqrt(365):null;
 const years=Math.max((end-start+1)/(365.2425*DAY),1/365.2425);
 const cagr=equity>0?(equity/10000)**(1/years)-1:-1;
 const rs=trades.map(t=>Number.isFinite(t.netR)?t.netR:t.riskBudget>0?t.net/t.riskBudget:null).filter(Number.isFinite);
 return {cagr,sharpe,expectancyR:rs.length?rs.reduce((s,v)=>s+v,0)/rs.length:null,
  averageTrade:trades.length?trades.reduce((s,t)=>s+t.net,0)/trades.length:null,
  calmar:maxDrawdown>0?cagr/maxDrawdown:null};
}

function riskCurve(curve){
 const days=new Map();for(const v of curve){const d=Math.floor(v.at/DAY),g=days.get(d)||{min:v,max:v,last:v};if(v.equity<g.min.equity)g.min=v;if(v.equity>g.max.equity)g.max=v;g.last=v;days.set(d,g);}
 return [...days.values()].flatMap(g=>[g.min,g.max,g.last].sort((a,b)=>a.at-b.at)).filter((v,i,a)=>!i||v.at!==a[i-1].at).map(v=>({at:v.at,equity:v.equity}));
}

function evaluate(market,maps,start,end,method,stress=false){
 const provider=(symbol,rows)=>X.apply(method,maps[symbol]?.get(rows.at(-1).end));
 const profile=stress?'selectorTargetsStress':'selectorTargets';
 const a=P.run(P.create('crypto',start,profile),sliceMarket(market,start,end),{mode:'replay',startAt:start,now:end+1,provider});
 const cfg=P.config(a);for(const p of [...a.positions])P.close(a,p,a.marks[p.symbol],a.marketAsOf,'평가 기간 종료',cfg,end,'close');
 const r=P.report(a);r.maxDrawdown=Math.max(r.maxDrawdown,1-r.equity/r.highWater);
 if(r.curve.length)r.curve.at(-1).equity=r.equity;
 if(Math.abs(r.equity-10000-r.trades.reduce((s,t)=>s+t.net,0))>1e-5)throw Error('Account reconciliation failure');
 let high=10000,peak=start,maxDuration=0;
 for(const v of r.curve){if(v.equity>=high){high=v.equity;peak=v.at;}else maxDuration=Math.max(maxDuration,v.at-peak);}
 const step=Math.max(1,Math.ceil(r.curve.length/240)),extra=metrics(r.curve,r.trades,start,end,r.equity,r.maxDrawdown);
 return {method:method.id,equity:r.equity,return:r.return,maxDrawdown:r.maxDrawdown,trades:r.trades.length,winRate:r.winRate,
  profitFactor:r.profitFactor,fees:r.fees,funding:r.funding,slippage:r.slippage,estimatedFundingHours:r.estimatedFundingHours,
  averageHoldHours:r.trades.length?r.trades.reduce((s,t)=>s+(t.exitAt-t.entryAt)/3600000,0)/r.trades.length:null,
  maxUnderwaterDays:maxDuration/DAY,unrecoveredAtEnd:r.equity<high,...extra,
  _riskCurve:riskCurve(r.curve),
  curve:r.curve.filter((v,i)=>i%step===0||i===r.curve.length-1).map(v=>({at:v.at,equity:v.equity})),
  closed:r.trades.map(t=>({symbol:t.symbol,side:t.side,entryAt:t.entryAt,exitAt:t.exitAt,entry:t.entry,exit:t.exit,qty:t.qty,net:t.net,netR:t.riskBudget>0?t.net/t.riskBudget:null,reason:t.exitReason}))};
}

function compact(r){const {curve,closed,_riskCurve,...rest}=r;return rest;}
function detail(r){const {_riskCurve,...rest}=r;return rest;}
function eligible(r){return r.trades>=30&&r.cagr>0&&(r.sharpe??-Infinity)>0&&(r.expectancyR??-Infinity)>0&&r.stress.return>0;}
function selectionScore(r){return r.cagr-r.maxDrawdown+.05*(r.sharpe??0);}
function combine(results){
 let scale=1,high=10000,dd=0;const curve=[],trades=[];
 for(const r of results){for(const v of r._riskCurve||r.curve){const equity=v.equity*scale;high=Math.max(high,equity);dd=Math.max(dd,1-equity/high);curve.push({at:v.at,equity});}for(const t of r.closed)trades.push({...t,net:t.net*scale});scale*=r.equity/10000;}
 const start=curve[0].at,end=curve.at(-1).at,equity=10000*scale,extra=metrics(curve,trades,start,end,equity,dd);
 return {equity,return:scale-1,maxDrawdown:dd,trades:trades.length,winRate:trades.length?trades.filter(t=>t.net>0).length/trades.length:null,...extra,curve};
}

function build(){
 const cache=process.env.PAPER_LONG_CACHE||'/tmp/paper-long-cache',marketFile=path.join(cache,'market.json'),manifestFile=path.join(cache,'manifest.json');
 const manifest=JSON.parse(fs.readFileSync(manifestFile));if(manifest.errors.length)throw Error('Incomplete archive data');
 const market=JSON.parse(fs.readFileSync(marketFile)),end=Math.min(...Object.values(manifest.coverage).map(v=>v.end)),lastYear=new Date(end).getUTCFullYear();
 const folder=path.join(ROOT,'simulation/exit-research');fs.mkdirSync(folder,{recursive:true});
 const maps=Object.fromEntries(Object.entries(market.crypto).map(([s,v])=>[s,T.signals(v.frames['15m'],'momentum14')]));
 const yearly=new Map();
 for(let year=2020;year<=lastYear;year++){
  const start=Date.UTC(year,0,1),finish=Math.min(end,Date.UTC(year+1,0,1)-1),results=[];
  for(const method of X.METHODS){
   const r=evaluate(market,maps,start,finish,method),stress=evaluate(market,maps,start,finish,method,true);r.stress=compact(stress);results.push(r);
   console.log(JSON.stringify({year,method:method.id,return:r.return,cagr:r.cagr,dd:r.maxDrawdown,sharpe:r.sharpe,expectancyR:r.expectancyR,stress:r.stress.return}));
  }
  yearly.set(year,{year,start,end:finish,results});
 }
 const periods=[];
 for(let year=2021;year<=lastYear;year++){
  const validation=yearly.get(year-1),test=yearly.get(year),eligibleRows=validation.results.filter(eligible);
  const selected=eligibleRows.length?[...eligibleRows].sort((a,b)=>selectionScore(b)-selectionScore(a)||X.METHODS.findIndex(x=>x.id===a.method)-X.METHODS.findIndex(x=>x.id===b.method))[0].method:'baseline';
  const selectedResult=test.results.find(r=>r.method===selected),base=test.results.find(r=>r.method==='baseline');
  periods.push({year,start:test.start,end:test.end,validationYear:year-1,selected,
   validationResults:validation.results.map(r=>({...compact(r),eligible:eligible(r),selectionScore:selectionScore(r)})),
   results:test.results.map(compact),baseline:detail(base),selectedResult:detail(selectedResult)});
 }
 const methodSummary=X.METHODS.map(method=>{const rows=periods.map(p=>yearly.get(p.year).results.find(r=>r.method===method.id)),combined=combine(rows);return {method:method.id,...compact(combined),positiveYears:rows.filter(r=>r.return>0).length,stressPositiveYears:rows.filter(r=>r.stress.return>0).length,worstAnnualDrawdown:Math.max(...rows.map(r=>r.maxDrawdown)),stressCompoundReturn:rows.reduce((v,r)=>v*(1+r.stress.return),1)-1};});
 const baseline=combine(periods.map(p=>yearly.get(p.year).results.find(r=>r.method==='baseline'))),walkForward=combine(periods.map(p=>yearly.get(p.year).results.find(r=>r.method===p.selected)));
 const plan={version:VERSION,createdAt:new Date().toISOString(),evaluationYears:periods.map(p=>p.year),validation:'Select one exit using only the preceding calendar year; 2026 evaluation ends at archive end.',entry:'Unchanged momentum14 signals on completed 4-hour bars; next 15-minute open execution.',methods:X.METHODS,selection:{eligibility:'At least 30 exits, positive CAGR, daily Sharpe, expectancy in initial-risk units, and positive doubled-cost return.',score:'CAGR - maximum drawdown + 0.05 × daily Sharpe. Fixed method order breaks exact ties.'},costs:'BTC 5x; ETH/SOL 3x. 1% risk budget, 3% total open risk, 0.045% fee and 0.02% slippage per side, observed funding. Stress doubles fees and slippage.',promotion:false,inputHashes:{market:hash(marketFile),manifest:hash(manifestFile)},sourceHashes:Object.fromEntries(['exit_methods.cjs','research_exit_methods.cjs','paper_engine.cjs','trend_methods.cjs'].map(f=>[f,hash(path.join(__dirname,f))]))};
 const report={version:VERSION,generatedAt:new Date().toISOString(),status:'과거 워크포워드 청산 연구 · 진행 계좌 적용 보류',deployed:false,dataEnd:end,coverage:manifest.coverage,methods:X.METHODS,plan:'plan.json',periods,methodSummary,
  combined:{baseline:compact(baseline),walkForward:compact(walkForward),selectedByYear:periods.map(p=>({year:p.year,method:p.selected,return:p.selectedResult.return,baselineReturn:p.baseline.return,maxDrawdown:p.selectedResult.maxDrawdown}))},
  conclusion:`${periods.length}개 다음연도 평가 중 수익 개선 ${periods.filter(p=>p.selectedResult.return>p.baseline.return).length}개, 낙폭 개선 ${periods.filter(p=>p.selectedResult.maxDrawdown<p.baseline.maxDrawdown).length}개. 새 미래 성과 전까지 진행 계좌는 변경하지 않습니다.`,
  notes:['모든 청산 후보는 결과 계산 전에 고정했습니다. 평가연도 결과로 그 해의 방식을 고르지 않았습니다.','CAGR과 일별 Sharpe는 각 독립 연도 및 연결 워크포워드 곡선에서 계산했습니다. 무위험 수익률은 0으로 둡니다.','거래당 기대값은 순손익을 진입 시 위험예산으로 나눈 R의 평균입니다. 승률만으로 우열을 정하지 않습니다.','각 연도 선택은 직전 연도 하나에 의존하므로 시장 국면 변화에 민감할 수 있습니다. 이미 살펴본 과거 자료이며 완전히 새로운 미래 검증이 아닙니다.','현재 BTC·ETH·SOL만 사용해 종목 선택·생존편향이 남습니다. 실제 호가 충격, 과거 수수료 등급, 정확한 마크가격 청산은 재현하지 않습니다.']};
 fs.writeFileSync(path.join(folder,'plan.json'),JSON.stringify(plan,null,2));fs.writeFileSync(path.join(folder,'latest.json'),JSON.stringify(report));
 console.log('COMPLETED',JSON.stringify({baseline:baseline.return,walkForward:walkForward.return,selections:report.combined.selectedByYear}));
}

if(require.main===module)build();module.exports={metrics,evaluate,eligible,selectionScore,combine,build};
