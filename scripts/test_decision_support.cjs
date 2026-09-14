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

// Calendar-day boundaries match Python, and cached values remain visible without
// turning missing/stale observations into usable risk signals.
const nowRisk=Date.parse('2026-09-14T20:00:00Z');
const riskSnapshot={generatedAt:'2026-09-14T19:00:00Z',indicators:[
 {id:'GZ_SPREAD',label:'GZ',status:'ready',asOf:'2026-07-01',maxAgeDays:75,value:.8,severity:0,unit:'%p',frequency:'monthly'},
 {id:'NFCI',label:'금융여건',status:'ready',asOf:'2026-09-04',maxAgeDays:16,value:0,severity:1,unit:'index',fetchStatus:'unavailable',fromCache:true},
 {id:'IORB',label:'IORB',status:'unavailable',asOf:'2026-09-11',maxAgeDays:5,value:3.65,severity:null,unit:'%'},
 {id:'DGS10',label:'국채 금리',status:'ready',asOf:'2026-09-11',maxAgeDays:7,value:null,change:1,severity:2,unit:'%'}
]};
let riskResult=D.risk(riskSnapshot,{},null,nowRisk);
assert.equal(riskResult.items[0].value,'0.80 %p');assert.equal(riskResult.items[0].severity,0);
assert.equal(riskResult.items[1].value,'0.00 index');assert(riskResult.items[1].detail.includes('수집 지연'));assert.equal(riskResult.items[1].severity,1);
assert.equal(riskResult.items[2].value,'3.65 %');assert.equal(riskResult.items[2].severity,null);
assert.equal(riskResult.items[3].value,'값 미확보');assert.equal(riskResult.items[3].severity,null);
riskResult=D.risk(riskSnapshot,{},null,nowRisk+86400000);
assert.equal(riskResult.items[0].value,'0.80 %p');assert.equal(riskResult.items[0].severity,null);assert(riskResult.items[0].detail.includes('판단 제외'));
assert(!JSON.stringify(riskResult).includes('NaN'));
console.log('Last-observation display, zero values, missing risk inputs and day-boundary checks passed');
