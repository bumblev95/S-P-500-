const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const A=require('../assets/stock-assessment.js');
const data=JSON.parse(fs.readFileSync('forecasts/latest.json'));
let clock=Date.parse(data.generatedAt)+86400000,selected='BRK.B',preferences={horizon:84},incoming=data;
class TestDate extends Date{static now(){return clock}}
const events={},root={innerHTML:'',clientWidth:900,addEventListener(type,fn){events[type]=fn}};
const context={StockAssessment:A,Date:TestDate,document:{getElementById:id=>id==='forecastPanel'?root:null},localStorage:{getItem:()=>JSON.stringify(preferences),setItem:(_,v)=>{preferences=JSON.parse(v)}},fetch:async()=>({ok:true,json:async()=>incoming}),setTimeout(){},clearTimeout(){},console};
context.window={forecastBridge:{selected:()=>selected,stocks:()=>[{symbol:'BRK.B',name:'Berkshire Hathaway'}],select:s=>{selected=s}},innerWidth:1000,addEventListener(){}};
vm.runInNewContext(fs.readFileSync('assets/forecast.js','utf8'),context);
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const click=h=>events.click({target:{closest:s=>s==='[data-fc-horizon]'?{dataset:{fcHorizon:String(h)}}:null}});
(async()=>{
 await settle();
 assert(root.innerHTML.includes('data-fc-horizon="126"'),'Legacy forecast must offer the supported 126-day period');
 assert(!root.innerHTML.includes('data-fc-horizon="84"'),'Obsolete saved periods must fall back to a supported period');
 assert(root.innerHTML.includes('BRK.B'));assert(!root.innerHTML.includes('예측 입력 데이터가 아직 없습니다'));
 assert(root.innerHTML.includes('126거래일 후'));assert(root.innerHTML.includes('기존 추세 전망'));
 click(252);assert(root.innerHTML.includes('252거래일 후'));assert.equal(preferences.horizon,252);
 const entry=A.entry(data,'BRK-B');
 assert(root.innerHTML.includes(entry.predictions[252].base.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})));
 clock=Date.parse(entry.asOf)+6*86400000;context.window.StockForecast.refresh();
 assert(root.innerHTML.includes('기준 종가 갱신 필요'));assert(!root.innerHTML.includes('fc-scenarios'));
 clock=Date.parse(data.generatedAt)+86400000;
 incoming=structuredClone(data);delete incoming.stocks[entry.symbol].predictions;delete incoming.stocks[entry.symbol].previous;
 events.click({target:{closest:s=>s==='[data-fc-reload]'?{}:null}});await settle();
 assert(root.innerHTML.includes('데이터 부족'));assert(!/NaN|undefined|Infinity/.test(root.innerHTML));
 console.log('Legacy forecast: dotted watchlist symbols, obsolete preferences, 126/252-day controls, distinct research label, stale/missing data passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
