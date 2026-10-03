'use strict';
const DAY=86400000,EPS=1e-10;
// Frozen screening policy. The production CLI has no switch to lower these gates.
const POLICY=Object.freeze({id:'shadow-promotion-screen-v1',minClosedTrades:100,minForwardDays:90,minEntryDates:30,
 purgedFolds:3,foldDays:30,minTrainTrades:30,minTrainDates:10,minTestTrades:20,embargoMs:DAY,minNetImprovement:.005,stressCostMultiplier:2,maxDrawdown:.10});
const sum=a=>a.reduce((s,x)=>s+x,0),mean=a=>a.length?sum(a)/a.length:null;
const finite=Number.isFinite,noWorse=(a,b)=>finite(a)&&finite(b)&&a<=b+EPS;
function slippage(t,cfg){
 const sign=t.side==='long'?1:-1;
 return Math.abs(t.entry-t.entry/(1+sign*cfg.slip))*t.qty+Math.abs(t.exit-t.exit/(1-sign*cfg.slip))*t.qty;
}
function tradeNet(t,cfg,stress=false){
 if(!finite(t.net)||!finite(t.entryFee)||!finite(t.exitFee)||!finite(t.funding)||!(t.riskBudget>0))return NaN;
 // Net already includes fees, funding and execution-price slippage. Only the
 // incremental stress cost is subtracted; embedded slippage is not charged twice.
 return t.net-(stress?(POLICY.stressCostMultiplier-1)*(t.entryFee+t.exitFee+slippage(t,cfg)):0);
}
function metrics(account,cfg){
 const curve=account.curve||[],trades=account.trades||[],initial=account.initial;
 let peak=initial,dd=0,maxExposure=0,maxOpenRisk=0,maxLeverage=0,maxEntryRisk=0,maxEntryExposure=0,maxConcurrentPositions=0;const days=new Map();
 for(const p of [...trades,...(account.positions||[])])maxLeverage=Math.max(maxLeverage,p.leverage||0);
 const intervals=[...trades,...(account.positions||[])];
 for(const v of curve){
  if(!(v.equity>0)||!finite(v.exposure))return {valid:false};
  peak=Math.max(peak,v.equity);dd=Math.max(dd,1-v.equity/peak);maxExposure=Math.max(maxExposure,v.exposure/v.equity);
  const open=intervals.filter(p=>p.entryAt<=v.at&&(p.exitAt===undefined||p.exitAt>v.at));
  maxOpenRisk=Math.max(maxOpenRisk,sum(open.map(p=>p.riskBudget))/v.equity);
  days.set(Math.floor(v.at/DAY),v.equity);
 }
 // Intrabar round trips still carried entry risk even when the closing mark is
 // flat. Normalize their known initial budgets/notionals by the preceding mark;
 // exact mark-price equity at an intrabar entry is not in the existing engine.
 for(const p of intervals){
  let lo=0,hi=curve.length;while(lo<hi){const mid=(lo+hi)>>1;if(curve[mid].at<p.entryAt)lo=mid+1;else hi=mid;}
  const before=curve[lo-1]?.equity??initial,open=intervals.filter(t=>t.entryAt<=p.entryAt&&(t.exitAt===undefined||t.exitAt>p.entryAt));
  maxEntryRisk=Math.max(maxEntryRisk,sum(open.map(t=>t.riskBudget))/before);
  maxEntryExposure=Math.max(maxEntryExposure,sum(open.map(t=>t.qty*t.entry))/before);maxConcurrentPositions=Math.max(maxConcurrentPositions,open.length);
 }
 const daily=[];let last=initial;for(const equity of days.values()){daily.push(equity/last-1);last=equity;}
 const avg=mean(daily),variance=daily.length?mean(daily.map(r=>(r-avg)**2)):null;
 const tail=[...daily].sort((a,b)=>a-b).slice(0,Math.max(1,Math.ceil(daily.length*.05)));
 const net=trades.map(t=>tradeNet(t,cfg)),stress=trades.map(t=>tradeNet(t,cfg,true)),entryDates=new Set(trades.map(t=>Math.floor(t.entryAt/DAY)));
 const expectancy=trades.map(t=>tradeNet(t,cfg)/t.riskBudget),stressExpectancy=trades.map(t=>tradeNet(t,cfg,true)/t.riskBudget);
 const unrealized=sum((account.positions||[]).map(p=>(p.side==='long'?1:-1)*p.qty*((account.marks?.[p.symbol]??p.entry)-p.entry)-p.entryFee-p.funding));
 const reconciled=curve.length&&finite(unrealized)&&Math.abs(curve.at(-1).equity-(initial+sum(net)+unrealized))<=1e-6;
 const chronology=curve.every((v,i)=>Number.isSafeInteger(v.at)&&(!i||v.at>curve[i-1].at));
 return {valid:initial===10000&&curve.length>0&&chronology&&reconciled&&[account.cash,account.fees,account.funding,account.slippage].every(finite)&&net.every(finite)&&stress.every(finite)&&intervals.every(p=>finite(p.riskBudget)&&p.riskBudget>0),
  closedTrades:trades.length,entryDates:entryDates.size,netReturn:sum(net)/initial,stressReturn:sum(stress)/initial,
  markedReturn:curve.length?curve.at(-1).equity/initial-1:null,expectancyR:mean(expectancy),stressExpectancyR:mean(stressExpectancy),
  maxDrawdown:dd,maxGrossExposure:maxExposure,maxOpenRisk,maxEntryRisk,maxEntryExposure,maxConcurrentPositions,maxLeverage,dailyVolatility:variance===null?null:Math.sqrt(variance),
  worstDailyLoss:daily.length?Math.max(0,-Math.min(...daily)):null,tailDailyLoss:tail.length?Math.max(0,-mean(tail)):null,
  funding:account.funding,estimatedFundingHours:account.estimatedFundingHours||0,fees:account.fees,slippage:account.slippage,
  openPositions:(account.positions||[]).length,pendingOrders:(account.pending||[]).length};
}
function matchedSample(candidate,accounts,observations){
 const a=accounts.incumbent,b=accounts.candidate;
 if(!a||!b||!observations.length)return {passed:false,reason:'No prospective paired observation'};
 const commonStart=a.createdAt===candidate.registeredAt&&b.createdAt===a.createdAt&&a.initial===10000&&b.initial===10000;
 const sameTimes=a.curve.length>0&&JSON.stringify(a.curve.map(v=>v.at))===JSON.stringify(b.curve.map(v=>v.at));
 const times=observations.map(r=>r.recordedAt),chronology=times.every((t,i)=>Number.isSafeInteger(t)&&t>=candidate.registeredAt&&(!i||t>times[i-1]));
 const noBackfill=[a,b].every(account=>account.events.every(e=>e.type!=='signal'||e.recordedAt>=candidate.registeredAt)&&account.trades.every(t=>t.orderCreatedAt>=candidate.registeredAt&&t.entryAt>=t.orderCreatedAt));
 return {passed:commonStart&&sameTimes&&chronology&&noBackfill,commonStart,identicalCurveTimes:sameTimes,chronology,noBackfill,
  observations:times.length,firstAt:times[0],lastAt:times.at(-1),forwardDays:a.startedAt===b.startedAt?(times.at(-1)-(a.startedAt??times.at(-1)))/DAY:0,
  comparison:'Whole paired accounts, including rejected signals, unfilled orders, cash and all losses; no matched-winner trade intersection.'};
}
function purgedWalkForward(candidate,history,accounts,asOf,cfg){
 const start=accounts.incumbent.startedAt??asOf,span=asOf-start,folds=[];
 if(span<POLICY.minForwardDays*DAY)return {passed:false,status:'insufficient',folds,reason:'Prospective time coverage below frozen minimum'};
 // Fixed 30-day test boundaries from the paired accounts' actual first run.
 // No fit/selection on a test window. Training is an auditable pool of completed
 // labels; signal groups stay together, and delayed publication is respected.
 const trainPool=[...history,...accounts.incumbent.trades];
 for(let i=0;i<Math.floor(span/(POLICY.foldDays*DAY));i++){
  const testStart=start+i*POLICY.foldDays*DAY,testEnd=testStart+POLICY.foldDays*DAY-1;
  const knownBefore=testStart-POLICY.embargoMs,groups=new Map();
  for(const t of trainPool){const key=t.signalAt;const g=groups.get(key)||[];g.push(t);groups.set(key,g);}
  const train=[...groups.values()].filter(g=>g.every(t=>Math.max(t.exitAt,t.recordedAt)<knownBefore&&t.signalAt<knownBefore)).flat();
  const take=trades=>trades.filter(t=>t.signalAt>=testStart&&t.orderCreatedAt>=testStart&&t.entryAt>=testStart&&t.exitAt<=testEnd&&t.recordedAt<=testEnd);
  const baseline=take(accounts.incumbent.trades),proposed=take(accounts.candidate.trades);
  const trainDates=new Set(train.map(t=>Math.floor(t.signalAt/DAY))).size;
  const sufficient=train.length>=POLICY.minTrainTrades&&trainDates>=POLICY.minTrainDates&&baseline.length>=POLICY.minTestTrades&&proposed.length>=POLICY.minTestTrades;
  const netBase=sum(baseline.map(t=>tradeNet(t,cfg))),netCandidate=sum(proposed.map(t=>tradeNet(t,cfg)));
  const stressBase=sum(baseline.map(t=>tradeNet(t,cfg,true))),stressCandidate=sum(proposed.map(t=>tradeNet(t,cfg,true)));
  const checks={enoughTrades:sufficient,positiveNet:netCandidate>0,netImprovement:netCandidate>netBase,positiveStress:stressCandidate>0,stressImprovement:stressCandidate>stressBase};
  folds.push({testStart,testEnd,trainingKnownBefore:knownBefore,trainTrades:train.length,trainDates,purgedTrainTrades:trainPool.length-train.length,
   trainingIds:train.map(t=>t.id),baselineTrades:baseline.length,candidateTrades:proposed.length,
   purgedBaselineTestTrades:accounts.incumbent.trades.length-baseline.length,purgedCandidateTestTrades:accounts.candidate.trades.length-proposed.length,
   netBase,netCandidate,stressBase,stressCandidate,checks,passed:Object.values(checks).every(v=>v===true)});
 }
 return {passed:folds.every(f=>f.passed),status:folds.some(f=>!f.checks.enoughTrades)?'insufficient':folds.every(f=>f.passed)?'passed':'failed',folds,
  method:'Frozen proposal; expanding completed-label pool; 24-hour embargo; purge overlapping or not-yet-published labels and boundary-crossing test trades. No retrospective fills or fold-specific refit.'};
}
function evaluate(candidate,history,accounts,observations,cfg,{integrity=true,completeData=true}={}){
 const matched=matchedSample(candidate,accounts,observations),baseline=metrics(accounts.incumbent,cfg),proposed=metrics(accounts.candidate,cfg),lastAt=observations.at(-1)?.recordedAt??candidate.registeredAt;
 const wf=purgedWalkForward(candidate,history,accounts,lastAt,cfg);
 const enough=baseline.closedTrades>=POLICY.minClosedTrades&&proposed.closedTrades>=POLICY.minClosedTrades&&baseline.entryDates>=POLICY.minEntryDates&&proposed.entryDates>=POLICY.minEntryDates&&matched.forwardDays>=POLICY.minForwardDays;
 const cost=baseline.valid&&proposed.valid&&proposed.netReturn>0&&proposed.markedReturn>0&&proposed.netReturn-baseline.netReturn>=POLICY.minNetImprovement&&proposed.markedReturn-baseline.markedReturn>=POLICY.minNetImprovement&&proposed.expectancyR>baseline.expectancyR&&proposed.stressReturn>0&&proposed.stressReturn-baseline.stressReturn>=POLICY.minNetImprovement&&proposed.stressExpectancyR>baseline.stressExpectancyR;
 const drawdown=noWorse(proposed.maxDrawdown,baseline.maxDrawdown)&&proposed.maxDrawdown<=POLICY.maxDrawdown;
 const risk=['maxGrossExposure','maxOpenRisk','maxEntryRisk','maxEntryExposure','maxConcurrentPositions','maxLeverage','dailyVolatility','worstDailyLoss','tailDailyLoss'].every(k=>noWorse(proposed[k],baseline[k]))&&proposed.maxConcurrentPositions<=cfg.maxPositions&&[accounts.incumbent,accounts.candidate].every(a=>!a.incompleteExecution&&!a.drawdownHalted&&!(a.isolatedLossAdjustment>0)&&!(a.estimatedFundingHours>0));
 const gates={immutableEvidence:integrity===true,completeData:completeData===true,matchedForwardSample:matched.passed,minimumTrades:enough,purgedWalkForward:wf.passed,costIncludedImprovement:cost,drawdownNotWorse:drawdown,riskNotWorse:risk};
 const eligible=Object.values(gates).every(v=>v===true);
 return {schemaVersion:1,mode:'shadow-only',candidateVersion:candidate.version,policy:POLICY,asOf:lastAt,
  status:eligible?'promotion_candidate':!enough||wf.status==='insufficient'?'insufficient':'rejected',promotionCandidate:eligible,
  automaticPromotion:false,defaultStrategyChanged:false,pinnedModelChanged:false,liveTrading:false,
  gates,failedGates:Object.entries(gates).filter(([,v])=>!v).map(([k])=>k),matchedForward:matched,purgedWalkForward:wf,incumbent:baseline,candidate:proposed};
}
module.exports={DAY,POLICY,slippage,tradeNet,metrics,matchedSample,purgedWalkForward,evaluate};
