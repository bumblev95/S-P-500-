const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const A=require('../assets/stock-assessment.js'),T=require('../assets/technical-guide.js'),L=require('../assets/learned-guide.js');
const key='sp500_sector_valuation_dashboard_ko_family_v25';
const fixture={selectedSymbol:'NVDA',selectedSector:'All',lastConstituentRefresh:Date.now(),settings:{years:3,analysisMode:3,autoSave:false},stocks:[{symbol:'NVDA',name:'Saved watch item',sector:'Watchlist',isCustom:true,watchlistSource:'local',price:200,forwardEPS:6,epsGrowth:10,revGrowth:8,grossMargin:40,opMargin:25,exitPE:22,discountRate:12,notes:'Keep my original note',risk:{rate:2,cyc:2,margin:2,balance:2,crowding:2,reg:2},fundamentalSource:'Saved manual assumptions'}]};
let clock=Date.now();class TestDate extends Date{static now(){return clock}}
const storage=new Map([[key,JSON.stringify(fixture)]]),nodes=new Map();
function node(id){
 if(!nodes.has(id)){const classes=new Set();nodes.set(id,{value:'',innerHTML:'',textContent:'',dataset:{},style:{},children:[],classList:{contains:x=>classes.has(x),toggle(x,v){if(v)classes.add(x);else classes.delete(x)},add:x=>classes.add(x),remove:x=>classes.delete(x)},appendChild(x){this.children.push(x)},replaceChildren(...xs){this.children=xs},setAttribute(k,v){this[k]=v},addEventListener(){},querySelectorAll(){return []},querySelector(){return null}});}
 return nodes.get(id);
}
const fetcher=async url=>{
 if(url.startsWith('config/'))return {ok:true,json:async()=>({sheetCsvUrl:'',submitUrl:''})};
 if(url.startsWith('custom_tickers'))return {ok:true,text:async()=> 'symbol,name\n'};
 const p=String(url).split('?')[0];return {ok:true,json:async()=>JSON.parse(fs.readFileSync(p)),text:async()=>fs.readFileSync(p,'utf8')};
};
const context={Date:TestDate,StockAssessment:A,TechnicalGuide:T,LearnedGuide:L,DecisionSupport:{load:async()=>{},applyStocks:x=>x},document:{getElementById:node,createElement:t=>node('generated-'+Math.random()),createDocumentFragment:()=>node('fragment-'+Math.random()),querySelectorAll:()=>[],body:node('body')},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},fetch:fetcher,setTimeout(){},console,alert(){},location:{reload(){}},navigator:{}};
context.window=context;
vm.runInNewContext(fs.readFileSync('advanced-legacy.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1],context);
(async()=>{
 await new Promise(resolve=>setImmediate(resolve));
 const data=JSON.parse(fs.readFileSync('forecasts/latest.json')),market=JSON.parse(fs.readFileSync('market/latest.json')),ml=JSON.parse(fs.readFileSync('ml/latest.json'));
 const expected=A.evaluate(data.stocks.NVDA,market,ml).score;
 assert.match(node('selectedDetails').innerHTML,new RegExp('data-trend-score="'+expected+'"'));
 const watch=node('watchlistTop').children.at(-1);assert(watch.innerHTML.includes(expected+'/100'));assert(watch.innerHTML.includes('관망'));
 assert.deepEqual(JSON.parse(storage.get(key)),fixture,'Loading shared scores must preserve saved watchlist/notes/assumptions');
 node('analysisMode').onchange({target:{value:'5'}});
 assert.match(node('selectedDetails').innerHTML,new RegExp('data-trend-score="'+expected+'"'));
 assert.deepEqual(JSON.parse(storage.get(key)),fixture,'Changing a manual comparison must not silently rewrite saved records');
 assert(!/NaN|undefined|Infinity/.test(node('selectedDetails').innerHTML));
 clock+=6*86400000;context.forecastBridge.select('NVDA');assert(node('selectedDetails').innerHTML.includes('산출 보류'));assert(!node('selectedDetails').innerHTML.includes('data-trend-score="'+expected+'"'));
 console.log(`Legacy watchlist/detail: ${expected}/100 matches the home calculation; manual-period changes leave the score unchanged; saved records preserved.`);
})().catch(e=>{console.error(e);process.exitCode=1});
