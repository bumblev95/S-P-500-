const assert=require('node:assert/strict'),D=require('../assets/decision-support.js');
const base={budget:1000,risk:50,entry:100,stop:90,target:120,fee:.001,slippage:.001};
let r=D.calculate(base);assert.equal(r.qty,4);assert(r.loss<=50);assert(r.margin+r.entryCost<=1000);assert(Math.abs(r.profit-78.24)<1e-8);
r=D.calculate({...base,futures:true,leverage:10,side:'short',stop:110,target:80,funding:-.0001,hours:24,liquidation:108});assert(r.funding>0);assert(r.liqBeforeStop);assert(r.loss<=50);
assert(D.calculate({...base,stop:101}).error);assert(D.calculate({...base,entry:0}).error);assert(D.calculate({...base,fee:-1}).error);assert(D.calculate({...base,leverage:Infinity}).error);
const pay=D.calculate({...base,futures:true,leverage:5,funding:.0001,hours:24,fractional:true});const receive=D.calculate({...base,futures:true,leverage:5,funding:-.0001,hours:24,fractional:true});assert(receive.funding<0);assert(receive.qty<=D.calculate({...base,futures:true,leverage:5,fractional:true}).qty);assert(pay.loss<=50);
assert.equal(D.risk(null,{}).status,'unknown');
const old={generatedAt:'2020-01-01',indicators:[{id:'GZ_SPREAD',label:'GZ',status:'ready',asOf:'2020-01-01',severity:0,value:1}]};assert.equal(D.risk(old,{}).coverage,0);
const html=D.confidence({dates:12,n:120,mape:.1,noChangeMape:.08,directionAccuracy:.6,p90Error:.3});assert(html.includes('제한적'));assert(html.includes('개선 확인 안 됨'));assert(html.includes('60.0%'));assert(!/NaN|undefined|Infinity/.test(html));
console.log('Trade costs, funding sign, quantity caps, invalid inputs and stale risk checks passed');

const stamp=new Date().toISOString().slice(0,10);assert(!D.risk(null,{X:{price:90,asOf:stamp,inputs:{ma200:100}}}).items.some(x=>x.label==='시장 상승 참여도'),'One stock cannot stand in for market breadth');
const metrics={mae:.1,p90:.2,directionAccuracy:.4,dates:4};
const experiment={generatedAt:'2026-09-12',horizons:{84:{sourceDates:12,correctionDates:7,comparison:{chosen:'regimeBlend',passed:false,improvementVsOriginal:.04,evaluation:{original:metrics,regimeBlend:{...metrics,mae:.096}},checks:{direction:false},selectionTargetThrough:'2025-01-01',evaluationStart:'2025-02-01'}}}};
const panel=D.adaptivePanel('X',84,experiment);assert(panel.includes('기본 예측 유지'));assert(panel.includes('4.0% 작았습니다'));assert(panel.includes('방향 적중률'));assert(!/undefined|NaN/.test(panel));
assert.equal(D.adaptivePanel('X',21,null),'');
const sparse=D.adaptivePanel('X',252,{horizons:{252:{sourceDates:5,correctionDates:0,comparison:{status:'insufficient'}}}});assert(sparse.includes('완료 시점이 부족'));assert(!sparse.includes('과거 비교 기준 통과'));
console.log('Adapter improvement, failed direction gate, and insufficient-history labels passed');
