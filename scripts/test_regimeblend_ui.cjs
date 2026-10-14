'use strict';
const assert=require('node:assert/strict');
const D=require('../assets/decision-support.js');
const model='completed-error-adapter-v1:pooled-hgb-pattern-v3-medium-long:regimeBlend';
const stamp=new Date().toISOString(),asOf=stamp.slice(0,10);
const summary={generatedAt:stamp,current:{stocks:{A:{126:{model,asOf,anchor:100,base:120,low:90,high:140,
 promoted:true,eligible:true,productionEligible:true,validation:{}}}},crypto:{}}};
global.fetch=async url=>({ok:true,json:async()=>url==='decision/latest.json'?summary:null});
const source=()=>({stocks:{A:{asOf,price:100,predictions:{126:{forecast:{anchor:100,base:105,bear:80,bull:130},status:'withheld'}}}}});
async function main(){
 await D.load();
 const stock=source(),before=JSON.stringify(stock);
 D.applyStocks(stock);
 assert.equal(JSON.stringify(stock),before,'Forged promotion and eligibility flags cannot put the quarantined adapter on the live chart');
 summary.current.stocks.A[126].model='existing-non-adapter';
 assert.equal(D.applyStocks(source()).stocks.A.predictions[126].forecast.base,120,'Keep existing non-adapter behavior');
 const metric={n:1996,dates:4,mae:.2,p90:.4,directionAccuracy:.4};
 const panel=D.adaptivePanel('A',126,{horizons:{126:{comparison:{chosen:'regimeBlend',chosenScope:'diagnostic-only',
  selectedCandidate:null,selectionEligible:false,passed:false,checks:{selectionEligible:false,mape:false,tailMape:false,
  balancedDirection:false,downRecall:false,upRecall:false,downPrecision:false,falseDown:false},
  evaluation:{original:metric,regimeBlend:metric},selectionTargetThrough:'2024-04-05',evaluationStart:'2024-10-04'},regimes:{}}}});
 assert(panel.includes('진단 후보'));
 assert(panel.includes('가격·방향 공동 선택'));
 assert(panel.includes('평균 가격 오차'));
 assert(!/undefined|NaN/.test(panel));
 assert(!panel.includes(' · 사전 선택'));
 console.log('Research labels and chart-level quarantine passed; existing non-adapter behavior preserved');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
