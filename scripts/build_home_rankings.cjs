'use strict';
const fs=require('node:fs'),path=require('node:path');
const assessment=require('../assets/stock-assessment.js');
const names=require('../assets/company-names.js');
const DAY=86400000;
const entryPriority=Object.freeze({buy:0,breakout:1,pullback:1,riskwait:2,overextended:3,confirm:4,watch:5,unavailable:6,avoid:7});
const holdingPriority=Object.freeze({reduce:0,protect:1,hold:2});
function select(assessments,now=Date.now()){
  const seen=new Set();
  const valid=Object.values(assessments||{}).filter(a=>{
    const age=a?(now-Date.parse(a.asOf))/DAY:NaN,symbol=assessment.normalize(a?.symbol);
    const ok=/^[A-Z0-9]+(?:[.-][A-Z0-9]+)?$/.test(symbol)&&!seen.has(symbol)&&
      Number.isFinite(a?.score)&&a.score>=0&&a.score<=100&&Number.isFinite(a.price)&&a.price>0&&
      /^\d{4}-\d{2}-\d{2}$/.test(a.asOf)&&Number.isFinite(age)&&age>=0&&age<=5&&
      new Date(a.asOf).toISOString().slice(0,10)===a.asOf&&
      Object.hasOwn(entryPriority,a.plan?.code)&&Object.hasOwn(holdingPriority,a.plan?.holding?.code);
    if(ok)seen.add(symbol);return ok;
  });
  // Every card uses the same latest observed close. Missing/stale quotes never
  // get padded with invented symbols or older sessions.
  const asOf=valid.reduce((date,a)=>a.asOf>date?a.asOf:date,'');
  const rows=valid.filter(a=>a.asOf===asOf);
  const buyTier=a=>a.plan.holding.code==='reduce'?8:entryPriority[a.plan.code];
  const buys=[...rows].sort((a,b)=>buyTier(a)-buyTier(b)||assessment.compare(a,b)).slice(0,3);
  const bought=new Set(buys.map(a=>assessment.normalize(a.symbol)));
  const compact=(a,type)=>({symbol:assessment.normalize(a.symbol),name:names[assessment.normalize(a.symbol)]?.[0]||a.symbol,
    asOf:a.asOf,score:a.score,code:a.plan.code,holdingCode:a.plan.holding.code,
    selection:type==='buy'&&a.plan.code==='buy'||type==='sell'&&a.plan.holding.code==='reduce'?'signal':'relative',
    reason:type==='buy'?a.reason:a.plan.holding.reason});
  return {
    buy:buys.map(a=>compact(a,'buy')),
    sell:rows.filter(a=>!bought.has(assessment.normalize(a.symbol)))
      .sort((a,b)=>holdingPriority[a.plan.holding.code]-holdingPriority[b.plan.holding.code]||assessment.compare(a,b,1))
      .slice(0,3).map(a=>compact(a,'sell')),
    asOf:asOf||null,eligibleCount:rows.length
  };
}
function build(root,now=Date.now()){
  const read=p=>JSON.parse(fs.readFileSync(path.join(root,p),'utf8'));
  const prices=read('forecasts/latest.json'),market=read('market/latest.json');
  return {...select(assessment.all(prices,market,null,126,now),now),evaluatedAt:new Date(now).toISOString(),
    priceGeneratedAt:prices.generatedAt,marketGeneratedAt:market.generatedAt,basis:'technical-relative-ranking',
    policy:'daily-top3-v1',
    priceMaxAgeDays:5,marketMaxAgeDays:3};
}
module.exports={select,build};
if(require.main===module){
  const root=process.argv[2]||path.resolve(__dirname,'..');
  process.stdout.write(JSON.stringify(build(root,process.argv[3]?Date.parse(process.argv[3]):Date.now())));
}
