const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const E = require('../assets/advanced-engine.js');
const V = require('../assets/market-visuals.js');
const L = require('../assets/learned-guide.js');
const A = require('../assets/stock-assessment.js');
const T = require('../assets/technical-guide.js');
const near = (a,b) => assert(Math.abs(a-b)<1e-9, `${a} != ${b}`);
const now = Date.parse('2026-09-11T12:00:00Z');
const sample = E.merge([{symbol:'BRK-B',close:120,date:'2026-09-11'}], [
  {symbol:'BRK.B',forwardEps:'',trailingEps:-2,debtToEquity:250,updatedAt:'2026-09-05'},
  {symbol:'LOSS',forwardEps:-1,updatedAt:'2026-08-01'}
],now);
assert.equal(sample.length,2);
assert.equal(sample[0].eps,null);
assert.equal(sample[0].pe,null);
assert.equal(sample[0].trailingPe,null);
assert.equal(sample[0].debtEquity,2.5);
assert.equal(sample[0].fundFresh,true);
assert.equal(sample[1].fundFresh,false);
assert.equal(E.filter(sample,{maxPe:30}).length,0);
assert.equal(E.filter(sample,{fresh:true}).length,1);
assert(!E.fresh('2027-01-01',7,now));
const config = {eps:5,growth:.1,pe:20,discount:.1,years:3,price:100};
const scenario = E.scenario(config);
near(scenario.terminalEPS,6.05);
near(scenario.present,121/1.331);
near(E.scenario({...config,growth:scenario.requiredGrowth}).present,100);
near(E.scenario({...config,years:1}).terminalEPS,5);
assert.equal(E.scenario({...config,years:1}).requiredGrowth,null);
for(const bad of [{eps:null},{eps:-1},{pe:0},{growth:-1},{years:2.5},{discount:-1}])
  assert.equal(E.scenario({...config,...bad}),null);
for(const dir of [1,-1])assert.equal(E.sort([{symbol:'A',pe:null},{symbol:'B',pe:4}], 'pe',dir).at(-1).symbol,'A');
assert.equal(E.csv('\uFEFFsymbol,name\r\nA,"Some, \"\"Co\"\""')[0].name,'Some, "Co"');
assert(E.exportCSV([{symbol:'=CMD()',name:'@bad',dd:-.2}]).includes("'=CMD()"));
assert(E.exportCSV([{symbol:'A',dd:-.2}]).includes('"-0.2"'));
const hist=Array.from({length:45},(_,i)=>({date:new Date(Date.UTC(2026,0,i+1)).toISOString().slice(0,10),close:100*Math.exp(.001*i+.02*Math.sin(i))}));
near(E.correlation(hist,hist).value,1);
assert.equal(E.correlation(hist.slice(0,20),hist.slice(0,20)).value,null);
assert.equal(E.correlation(hist.map(r=>({...r,close:100})),hist).value,null);
const missing=hist.filter((r,i)=>i!==5);
assert.equal(E.correlation(hist,missing).n,42); // Both endpoints must agree; never pair a 2-day and 1-day return.
const chart=E.comparison([{symbol:'A',history:hist},{symbol:'B',history:missing}],252);
assert.equal(chart.dates.length,44);
assert(chart.series.every(s=>s.values[0]===100));
assert.equal(E.metrics(missing,hist.map(r=>r.date)).vol,null);
near(E.metrics([{date:'a',close:100},{date:'b',close:80},{date:'c',close:120}]).drawdown,-.2);
const prices=E.csv(fs.readFileSync('prices/latest_prices.csv','utf8'));
const funds=E.csv(fs.readFileSync('fundamentals/latest_fundamentals.csv','utf8'));
const actual=E.merge(prices,funds,now);
assert(actual.length>=400);
for(const r of actual){if(r.pe!==null)near(r.pe,r.price/r.eps);if(r.eps===null)assert.equal(r.pe,null);}

// Lightweight DOM harness covers async loading, tab routing, filters, and failed refreshes.
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',innerHTML:'',textContent:'',checked:false,hidden:false,dataset:{},events:{},addEventListener(type,fn){this.events[type]=fn},setAttribute(){},insertAdjacentHTML(_,html){this.innerHTML=html+this.innerHTML}});return nodes.get(id)}
const tabs=['screen','compare','value','validation'].map(view=>Object.assign(node('tab-'+view),{dataset:{view}}));
let fail=false;
const snapshot=JSON.parse(fs.readFileSync('forecasts/latest.json')),market=JSON.parse(fs.readFileSync('market/latest.json')),ml=JSON.parse(fs.readFileSync('ml/latest.json'));
let clock=Date.parse(market.generatedAt),exported='',marketPayload=market;
class TestDate extends Date{constructor(...args){super(...(args.length?args:[clock]))}static now(){return clock}}
const context={AdvancedEngine:E,MarketVisuals:V,LearnedGuide:L,StockAssessment:{...A,all:(d,m,l,h)=>A.all(d,m,l,h,clock),evaluate:(e,m,l,h)=>A.evaluate(e,m,l,h,clock)},TechnicalGuide:{...T,marketState:m=>T.marketState(m,clock)},DecisionSupport:{load:async()=>{},applyStocks:x=>x},document:{getElementById:node,createElement:()=>({click(){}}),querySelectorAll:s=>s==='[data-view]'?tabs:s==='[data-assumption]'?[...node('content').innerHTML.matchAll(/data-assumption="([^"]+)"[^>]*value="([^"]*)"/g)].map(m=>{const n=node('assumption-'+m[1]);n.dataset.assumption=m[1];if(n.value==='')n.value=m[2];return n}):[],hidden:false},localStorage:{getItem:()=>null,setItem(){}},fetch:async url=>{if(fail)throw Error('offline');return {ok:true,text:async()=>fs.readFileSync(url,'utf8'),json:async()=>url.startsWith('market/')?marketPayload:JSON.parse(fs.readFileSync(url,'utf8'))}},Blob:class{constructor(parts){exported=parts.join('')}},URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},setInterval(){},setTimeout(){},console,Intl,Date:TestDate};
vm.runInNewContext(fs.readFileSync('assets/advanced-page.js','utf8'),context);
const settle=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  await settle();
  assert(node('content').innerHTML.includes('종목 스크리너'));
  const expected=A.rank(A.all(snapshot,market,ml,126,clock),Infinity).filter(a=>actual.some(r=>A.normalize(r.symbol)===A.normalize(a.symbol))).slice(0,40).map(a=>A.normalize(a.symbol));
  assert.deepEqual([...node('content').innerHTML.matchAll(/data-symbol="([^"]+)"/g)].map(m=>A.normalize(m[1])),expected,'Default screener order must match the home score ranking');
  for(const sym of ['BRK.B','BF.B']){
    node('search').value=sym;node('search').events.input();
    const a=A.evaluate(A.entry(snapshot,sym),market,ml,126,clock);
    assert(node('content').innerHTML.includes(a.score+'/100'),sym+' must resolve the canonical assessment');
    node('asset').value=sym;node('asset').events.change();
    assert.match(node('inspector').innerHTML,new RegExp('data-trend-score="'+a.score+'"'));
    node('export').events.click();
    const row=E.csv(exported)[0];
    assert.equal(Number(row.trendScore),a.score);assert.equal(row.scoreAsOf,a.asOf);assert.equal(Number(row.scorePrice),a.price);
    assert.equal(row.entryDecision,a.decision);assert.equal(row.modelStatus,a.modelStatus);assert.equal(Number(row.assessmentHorizon),126);
    node('tab-validation').events.click();await settle();
    assert(!node('content').innerHTML.includes('선택 종목의 예측 자료가 없습니다'),sym+' validation must resolve the same alias');
    node('tab-screen').events.click();
  }
  node('asset').value='NVDA';node('asset').events.change();
  node('search').value='NVDA';node('search').events.input();
  assert(node('content').innerHTML.includes('1개 결과'));
  for(const view of ['compare','value','validation']){
    node('tab-'+view).events.click();await settle();
    const html=node('content').innerHTML;
    assert(html.length>1000);
    assert(!/NaN|undefined|Infinity/.test(html),view);
  }
  node('tab-value').events.click();
  const inputs=context.document.querySelectorAll('[data-assumption]');
  for(const n of inputs)n.value=String({eps:5,growth:10,pe:20,discount:10,years:3}[n.dataset.assumption]);
  node('applyAssumptions').events.click();
  assert(node('content').innerHTML.includes('이 기기에 저장된 사용자 가정'));
  assert(node('content').innerHTML.includes('value="10"'));
  const changed=E.scenario({...config,price:actual.find(r=>r.symbol==='NVDA').price});
  assert(node('content').innerHTML.includes(changed.present.toLocaleString('en-US',{maximumFractionDigits:2})));
  node('tab-compare').events.click();await settle();
  node('analysisHorizon').events.change({target:{value:'252'}});
  const year=A.evaluate(snapshot.stocks.NVDA,market,ml,252,clock);
  assert.match(node('inspector').innerHTML,new RegExp('data-trend-score="'+year.score+'"'));
  assert(node('inspector').innerHTML.includes(year.modelStatus));
  node('export').events.click();assert.equal(Number(E.csv(exported)[0].assessmentHorizon),252);
  if(JSON.parse(fs.readFileSync('forecasts/latest.json')).stocks.NVDA.history.length<253)
    assert(node('content').innerHTML.includes('공통 이력이 짧습니다'));
  marketPayload={generatedAt:new Date(clock).toISOString(),credit:{status:'stable'},indicators:[]};
  await node('refresh').events.click();await settle();
  assert.match(node('sourceStatus').innerHTML,/<span>미국 신용시장<\/span><b[^>]*>자료 확인 필요/,'A fresh timestamp alone must not hide missing market indicators');
  // No reload or horizon change: an export and an ordinary filter render must expire cached scores.
  clock+=6*86400000;
  node('export').events.click();assert.equal(E.csv(exported)[0].trendScore,'');assert.equal(E.csv(exported)[0].entryDecision,'판단 보류');
  node('tab-screen').events.click();node('search').events.input();
  assert(node('content').innerHTML.includes('산출 보류'));assert(node('inspector').innerHTML.includes('판단 보류'));
  assert(node('sourceStatus').innerHTML.includes('자료 확인 필요'),'Stale market status must agree with the shared entry gate');
  fail=true;await node('refresh').events.click();await settle();
  assert(node('sourceStatus').innerHTML.includes('읽기 실패'));
  assert.equal(node('inspector').innerHTML,'');
  console.log('Advanced: canonical aliases/ranking, table/detail/CSV metadata, 126/252-day switching, time-expired exports, market gate, calculations, four views and failure states passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
