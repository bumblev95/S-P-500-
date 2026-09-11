const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const guide=require('../assets/technical-guide.js'),data=JSON.parse(fs.readFileSync('forecasts/latest.json')),market=JSON.parse(fs.readFileSync('market/latest.json'));
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
const nodes=new Map(),node=id=>nodes.get(id)||nodes.set(id,{innerHTML:'',value:'NVDA',textContent:'',classList:{remove(){},toggle(){}},addEventListener(){},querySelectorAll(){return []}}).get(id);
const context={TradeJournal:{mount(){}},ForecastPath:require('../assets/forecast-path.js'),TechnicalGuide:guide,LearnedGuide:require('../assets/learned-guide.js'),MarketContext:{render(){}},document:{querySelector:node,querySelectorAll:()=>[]},window:{scrollTo(){}},fetch:async url=>({ok:true,json:async()=>url.startsWith('forecasts')?data:url.startsWith('market')?market:null}),console};
vm.runInNewContext(fs.readFileSync('beginner.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1],context);
setImmediate(()=>{assert(node('#app').innerHTML.includes('기술 지표'));assert(!/NaN|Infinity/.test(node('#app').innerHTML));console.log(`${count} plans, missing/stale guards, RSI/MACD flat series, page render passed`);});
