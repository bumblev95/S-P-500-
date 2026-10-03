const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const A=require('../assets/stock-assessment.js'),T=require('../assets/technical-guide.js'),L=require('../assets/learned-guide.js');
const key='sp500_sector_valuation_dashboard_ko_family_v25';
const fixture={selectedSymbol:'NVDA',selectedSector:'All',lastConstituentRefresh:Date.now(),settings:{years:3,analysisMode:3,autoSave:false},stocks:[{symbol:'NVDA',name:'Saved watch item',sector:'Watchlist',isCustom:true,watchlistSource:'local',price:200,forwardEPS:6,epsGrowth:10,revGrowth:8,grossMargin:40,opMargin:25,exitPE:22,discountRate:12,notes:'Keep my original note',risk:{rate:2,cyc:2,margin:2,balance:2,crowding:2,reg:2},fundamentalSource:'Saved manual assumptions'}]};
let clock=Date.parse(JSON.parse(fs.readFileSync('market/latest.json')).generatedAt);class TestDate extends Date{static now(){return clock}}
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
 const expected=A.evaluate(data.stocks.NVDA,market,ml,126,clock).score;
 assert.match(node('selectedDetails').innerHTML,new RegExp('data-trend-score="'+expected+'"'));
 const watch=node('watchlistTop').children.at(-1);assert(watch.innerHTML.includes(expected+'/100'));assert(watch.innerHTML.includes('관망'));
 assert.deepEqual(JSON.parse(storage.get(key)),fixture,'Loading shared scores must preserve saved watchlist/notes/assumptions');
 node('analysisMode').onchange({target:{value:'5'}});
 assert.match(node('selectedDetails').innerHTML,new RegExp('data-trend-score="'+expected+'"'));
 assert.deepEqual(JSON.parse(storage.get(key)),fixture,'Changing a manual comparison must not silently rewrite saved records');
 assert(!/NaN|undefined|Infinity/.test(node('selectedDetails').innerHTML));
 context.testAlias={...fixture.stocks[0],symbol:'BRK.B'};
 vm.runInNewContext('state.stocks.push(testAlias)',context);
 context.forecastBridge.select('BRK-B');
 const alias=A.evaluate(A.entry(data,'BRK-B'),market,ml,126,clock);
 assert.match(node('selectedDetails').innerHTML,new RegExp('data-trend-score="'+alias.score+'"'),'Forecast selections must resolve dotted saved-watchlist symbols');
 const day=new Date(clock).toISOString().slice(0,10),history=Array.from({length:80},(_,i)=>({date:new Date(Date.parse(day)-(79-i)*86400000).toISOString().slice(0,10),close:300-i-i*i*.02}));
 const zero={symbol:'AAA',status:'ready',fresh:true,asOf:day,price:history.at(-1).close,history,inputs:{ma20:120,ma50:140,ma200:160,return1m:-.1,return3m:-.1,volatility4m:.2}};
 assert.equal(A.evaluate(zero,market,null,126,clock).score,0,'Control must have a valid zero score');
 context.testSnapshot={data:{stocks:{AAA:zero,ZZZ:{...zero,symbol:'ZZZ'}}},market,learned:null};
 context.testStocks=['ZZZ','BBB','AAA'].map(symbol=>({...fixture.stocks[0],symbol}));
 vm.runInNewContext('canonicalSnapshot=testSnapshot;state.stocks=testStocks;state.selectedSymbol="AAA";render()',context);
 const cards=node('mobileStockList').children.slice(-3);
 assert.deepEqual(cards.map(c=>c.innerHTML.match(/class="mobileTicker">([^<]+)/)[1]),['AAA','ZZZ','BBB'],'Mobile ranking must keep a real zero before missing data and break ties by ticker');
 clock+=6*86400000;context.setMobileMode(true);
 assert(node('selectedDetails').innerHTML.includes('산출 보류'),'Changing mobile mode must expire cached assessments');
 assert(!node('selectedDetails').innerHTML.includes('data-trend-score="0"'));
 assert.deepEqual(JSON.parse(storage.get(key)),fixture,'Alias selection and mobile rendering must preserve saved records');
 const archive=fs.readFileSync('family-v24-archive.html','utf8');
 assert(archive.includes('보관 화면')&&archive.includes('공통 단기 추세 점수'),'The reachable historical archive must identify its obsolete scoring rules');
 console.log(`Legacy: ${expected}/100 matches home; alias selection, valid-zero/missing/tied mobile order, cache expiry, archive disclosure and saved records passed.`);
})().catch(e=>{console.error(e);process.exitCode=1});
