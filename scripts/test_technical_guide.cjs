const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const guide=require('../assets/technical-guide.js'),data=JSON.parse(fs.readFileSync('forecasts/latest.json')),market=JSON.parse(fs.readFileSync('market/latest.json'));
const learned=JSON.parse(fs.readFileSync('ml/latest.json'));
const now=Date.parse(market.generatedAt);
assert.equal(guide.marketState(market,now),market.credit.status);
assert.equal(guide.marketState(market,now+10*86400000),'unknown');
assert.equal(guide.marketState(null,now),'unknown');
let count=0;
for(const e of Object.values(data.stocks))for(const p of Object.values(e.predictions||{})){
  const plan=guide.plan(e,p,market,now);assert(Number.isFinite(plan.ts));
  if(!e.history?.length)assert.notEqual(plan.tone,'buy');
  if(plan.target1){assert(plan.target1>plan.buyHigh);assert(Math.abs(plan.rr-(plan.target1-plan.buyHigh)/(plan.buyHigh-plan.stop))<1e-10);}
  if(plan.target2)assert(plan.target2>plan.target1);
  assert.notEqual(guide.plan(e,p,null,now).tone,'buy');count++;
}
const flat={price:100,asOf:'2026-09-10',history:Array.from({length:70},(_,i)=>({date:new Date(Date.parse('2026-07-03')+i*86400000).toISOString().slice(0,10),close:100}))};
flat.asOf=flat.history.at(-1).date;assert.equal(guide.indicators(flat).rsi,50);assert.equal(guide.indicators(flat).macd,0);assert.equal(guide.indicators(flat).z,0);
const nodes=new Map(),node=id=>nodes.get(id)||nodes.set(id,{innerHTML:'',value:'NVDA',textContent:'',dataset:{},events:{},classList:{remove(){},toggle(){}},addEventListener(type,fn){this.events[type]=fn},querySelectorAll(){return []}}).get(id);
const buttons=[126,252].map(h=>Object.assign(node('h'+h),{dataset:{h:String(h)}})),A=require('../assets/stock-assessment.js');let clock=now;
const context={DecisionSupport:{load:async()=>{},applyStocks:x=>x,mountStock(){}},StabilityPanel:require('../assets/stability-panel.js'),TradeJournal:{mount(){}},ForecastPath:require('../assets/forecast-path.js'),StockAssessment:{...A,evaluate:(e,m,l,h)=>A.evaluate(e,m,l,h,clock),all:(d,m,l,h)=>A.all(d,m,l,h,clock)},TechnicalGuide:guide,LearnedGuide:require('../assets/learned-guide.js'),MarketContext:{render(){}},document:{querySelector:node,querySelectorAll:s=>s==='[data-h]'?buttons:[]},window:{scrollTo(){}},fetch:async url=>({ok:true,json:async()=>url.startsWith('forecasts')?data:url.startsWith('market')?market:url.startsWith('ml/latest')?learned:null}),console};
vm.runInNewContext(fs.readFileSync('index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1],context);
setImmediate(()=>{
 const nvda=data.stocks.NVDA,ai=context.LearnedGuide.inspect(learned,nvda,126),shown=ai.researchForecast||nvda.predictions[126];
 assert(node('#app').innerHTML.includes('기술 지표'));assert(node('#app').innerHTML.includes(ai.researchForecast?'AI 연구 전망 · 검증 미통과':'AI 연구 자료 없음'));assert(node('#app').innerHTML.includes('$'+shown.base.toFixed(2)));assert(node('#app').innerHTML.includes('3년 가치 시나리오'));assert(!node('#app').innerHTML.includes('AI 전망 판단 보류'));assert(!/NaN|Infinity/.test(node('#app').innerHTML));
 for(const [i,h] of [126,252].entries()){
  buttons[i].events.click();const a=A.evaluate(nvda,market,learned,h,clock);
  assert.match(node('#app').innerHTML,new RegExp('data-trend-score="'+a.score+'"'));
  const actual=[...node('#candidateRail').innerHTML.matchAll(/data-trend-symbol="([^"]+)" data-trend-score="([^"]+)"/g)].map(m=>[m[1],Number(m[2])]);
  assert.deepEqual(actual,A.rank(A.all(data,market,learned,h,clock)).map(a=>[a.symbol,a.score]));
 }
 node('#tickerInput').events.change({target:{value:'KEYS'}});
 const expected=A.evaluate(data.stocks.KEYS,market,learned,126,clock).score;
 data.stocks.KEYS.predictions={};learned.stocks.KEYS.predictions={};buttons[0].events.click();
 assert.match(node('#app').innerHTML,new RegExp('data-trend-score="'+expected+'"'));assert(node('#app').innerHTML.includes('선택 기간의 전망 자료가 부족합니다'));
 clock+=6*86400000;buttons[1].events.click();assert(node('#app').innerHTML.includes('산출 보류'));assert(!/data-trend-score="\d/.test(node('#candidateRail').innerHTML));
 console.log(`${count} technical plans; home candidate/detail parity, 126/252-day controls, missing forecasts, expiry and flat-series guards passed (DOM harness).`);
});
