'use strict';
const fs=require('node:fs'),readline=require('node:readline'),P=require('./paper_engine.cjs'),T=require('./trend_methods.cjs'),R=require('./research_trend_methods.cjs'),{sliceMarket}=require('./research_momentum_cpd.cjs');
const market=JSON.parse(fs.readFileSync('/tmp/paper-long-cache/market.json'));
const maps=Object.fromEntries(Object.entries(market.crypto).map(([s,v])=>[s,T.signals(v.frames['15m'],'momentum14')]));
function evaluate(req,stress=false){
 const scores=req.scores?new Map(req.scores.map(r=>[r[0]+':'+r[1],r[2]])):null;
 const provider=(s,rows)=>{
  const at=rows.at(-1).end,original=maps[s].get(at);if(!original)return {side:null};
  const q={...original};
  if(scores&&q.side&&!(scores.get(s+':'+at)>=.10))q.side=null;
  if(req.exit==='fixed2r')q.trailLong=q.trailShort=null;
  if(q.side&&req.exit&&req.exit!=='trailing')q.target=q.price+(q.side==='long'?1:-1)*(req.exit==='fixed2r'?5:4)*q.atr;
  return q;
 };
 const targets=req.exit&&req.exit!=='trailing',profile=targets?(stress?'selectorTargetsStress':'selectorTargets'):(stress?'trendResearchStress':'trendResearch');
 const a=P.run(P.create('crypto',req.start,profile),sliceMarket(market,req.start,req.end),{mode:'replay',startAt:req.start,now:req.end+1,provider});
 for(const p of [...a.positions])P.close(a,p,a.marks[p.symbol],a.marketAsOf,'평가 기간 종료',P.config(a),req.end,'close');
 const r=P.report(a);r.maxDrawdown=Math.max(r.maxDrawdown,1-r.equity/r.highWater);
 if(r.curve.length)r.curve.at(-1).equity=r.equity;
 if(Math.abs(r.equity-10000-r.trades.reduce((s,t)=>s+t.net,0))>1e-5)throw Error('Account reconciliation failure');
 let high=10000,peak=req.start,maxDuration=0;
 for(const v of r.curve){if(v.equity>=high){high=v.equity;peak=v.at;}else maxDuration=Math.max(maxDuration,v.at-peak);}
 const step=Math.max(1,Math.ceil(r.curve.length/240));
 return {equity:r.equity,return:r.return,maxDrawdown:r.maxDrawdown,trades:r.trades.length,winRate:r.winRate,fees:r.fees,funding:r.funding,slippage:r.slippage,estimatedFundingHours:r.estimatedFundingHours,warnings:r.warnings,maxUnderwaterDays:maxDuration/86400000,unrecoveredAtEnd:r.equity<high,profitFactor:r.profitFactor,
 curve:req.compact?undefined:r.curve.filter((v,i)=>i%step===0||i===r.curve.length-1).map(v=>({at:v.at,equity:v.equity})),
 closed:req.compact?undefined:r.trades.map(t=>({symbol:t.symbol,side:t.side,entryAt:t.entryAt,exitAt:t.exitAt,entry:t.entry,exit:t.exit,qty:t.qty,net:t.net,fees:t.entryFee+t.exitFee,funding:t.funding,reason:t.exitReason}))};
}
const rl=readline.createInterface({input:process.stdin});rl.on('line',line=>{try{const req=JSON.parse(line),r=evaluate(req);if(req.stress){const s=evaluate({...req,compact:true},true);r.stress={return:s.return,maxDrawdown:s.maxDrawdown,equity:s.equity};}process.stdout.write(JSON.stringify(r)+'\n');}catch(e){process.stdout.write(JSON.stringify({error:e.stack})+'\n');}});
