'use strict';
const fs=require('node:fs'),path=require('node:path');
const assessment=require('../assets/stock-assessment.js');
const names=require('../assets/company-names.js');
const waitingCodes=new Set(['breakout','pullback','riskwait']);
function select(assessments){
  const rows=Object.values(assessments||{}).filter(a=>Number.isFinite(a.score));
  const compact=a=>({symbol:a.symbol,name:names[a.symbol]?.[0]||a.symbol,asOf:a.asOf});
  const buy=rows.filter(a=>a.plan?.code==='buy').sort(assessment.compare).slice(0,3).map(compact);
  return {
    buy,
    // Waiting states never fill or change the actual buy ranking.
    waiting:buy.length?[]:rows.filter(a=>waitingCodes.has(a.plan?.code)).sort(assessment.compare).slice(0,3)
      .map(a=>({...compact(a),code:a.plan.code})),
    sell:rows.filter(a=>a.plan?.holding?.code==='reduce').sort((a,b)=>assessment.compare(a,b,1)).slice(0,3).map(compact)
  };
}
function build(root,now=Date.now()){
  const read=p=>JSON.parse(fs.readFileSync(path.join(root,p),'utf8'));
  const prices=read('forecasts/latest.json'),market=read('market/latest.json');
  return {...select(assessment.all(prices,market,null,126,now)),evaluatedAt:new Date(now).toISOString(),
    priceGeneratedAt:prices.generatedAt,marketGeneratedAt:market.generatedAt,basis:'technical-rules',
    priceMaxAgeDays:5,marketMaxAgeDays:3};
}
module.exports={select,build};
if(require.main===module){
  const root=process.argv[2]||path.resolve(__dirname,'..');
  process.stdout.write(JSON.stringify(build(root)));
}
