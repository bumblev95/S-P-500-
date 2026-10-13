const assert=require('node:assert/strict'),fs=require('node:fs');
const S=require('../assets/company-search.js'),E=require('../assets/advanced-engine.js');
const funds=E.csv(fs.readFileSync('fundamentals/latest_fundamentals.csv','utf8'));
const items=funds.map(row=>({symbol:row.symbol,name:row.shortName}));
const symbols=query=>S.search(items,query,Infinity).map(row=>row.symbol);
for(const [query,expected] of [['엔비디아','NVDA'],['엔비','NVDA'],['애플','AAPL'],
 ['마이크로 소프트','MSFT'],['마소','MSFT'],['테슬라','TSLA'],['페이스북','META'],
 ['브로드컴','AVGO'],['코카 콜라','KO'],['피앤지','PG'],['셰브론','CVX'],
 ['NVDA','NVDA'],['nvda','NVDA'],['ＮＶＤＡ','NVDA'],['Nvidia','NVDA'],
 ['NVDA 엔비디아','NVDA'],['NVDA NVIDIA','NVDA'],
 ['Apple','AAPL'],['BRK.B','BRK.B'],['brk-b','BRK.B'],['버크셔 헤서웨이','BRK.B'],
 ['알파벳 A','GOOGL'],['알파벳 C','GOOG']]){
 assert.equal(S.resolve(items,query)?.symbol,expected,query);
}
for(const [query,expected] of [['트윌리오','TWLO'],['Twilio Inc.','TWLO'],['바일러','VYLR'],['Vylor Inc.','VYLR']])
 assert.equal(S.resolve(items,query)?.symbol,expected,query);
assert.deepEqual(symbols('구글'),['GOOG','GOOGL']);
assert.equal(S.resolve(items,'구글'),null,'Shared names must not choose a share class implicitly');
assert.equal(S.resolve(items,'Alphabet Inc.'),null);
assert.equal(S.resolve(items,'마이크로'),null,'Partial names matching several companies require a selection');
assert.equal(S.resolve(items,'없는회사이름'),null);
assert.deepEqual(symbols('---'),[]);
assert.deepEqual(symbols('<script>alert(1)</script>'),[]);
assert.deepEqual(S.search([{symbol:'AAPL'}],'테슬라'),[],'The alias catalog must not expand the available data universe');
assert.equal(S.name('__proto__','Unknown Company'),'Unknown Company');
assert.equal(S.koreanName('NEW'), '');
assert.equal(S.name('NEW','New Company'), 'New Company');
assert.equal(S.resolve([{symbol:'NEW',name:'새 회사'}],'새회사').symbol,'NEW');
assert.equal(S.resolve([{symbol:'BRK.B'},{symbol:'BRK-B'}],'BRK-B').symbol,'BRK.B');
assert.equal(S.resolve([...items,{symbol:'GOOGLE',name:'Another Company'}],'GOOGLE').symbol,'GOOGLE','An exact available ticker outranks shared company aliases');
const before=JSON.stringify(items);
for(const item of items)assert(S.koreanName(item.symbol),item.symbol+' requires a display label');
S.search(items,'마이크로',3);assert.equal(JSON.stringify(items),before,'Search must not modify financial records');
const merged=E.merge([],funds);
assert.deepEqual(E.filter(merged,{search:'구글'}).map(row=>row.symbol),['GOOG','GOOGL']);
assert.deepEqual(E.filter(merged,{search:'엔비디아'}).map(row=>row.symbol),['NVDA']);
assert.deepEqual(E.filter(merged,{search:'brk-b'}).map(row=>row.symbol),['BRK.B']);
const nvda=merged.find(row=>row.symbol==='NVDA');
assert.equal(nvda.nameKo,'엔비디아');
assert.equal(nvda.name,'NVIDIA Corporation','Keep the original English source name');
assert.equal(E.csv(E.exportCSV([nvda]))[0].nameKo,'엔비디아');

// Provider/source snapshots use SKYD; retained EOD/archive keys may use PSKY.
// These aliases identify search terms, never permission to rewrite history.
const old=Object.freeze({symbol:'PSKY',name:'Paramount Skydance Corporation'});
const current=Object.freeze({symbol:'SKYD',name:'Paramount Skydance Corporation'});
const renamed=Object.freeze({symbol:'SKYD',name:'Skydance Corporation'});
const aliases=['PSKY','psky','SKYD','skyd','ＳＫＹＤ','파라마운트','파라마운트 스카이댄스',
 '스카이댄스','스카이 댄스','Paramount Skydance Corporation','Skydance Corporation',
 'skydance'];
assert.equal(S.koreanName('PSKY'),'파라마운트 스카이댄스');
assert.equal(S.koreanName('SKYD'),'스카이댄스');
assert.equal(S.englishName('SKYD'),'Skydance Corporation');
assert.equal(S.englishName('SKYD',current.name),current.name,'Preserve provider names');
for(const item of [old,current,renamed]){
 for(const query of aliases){
  assert.equal(S.resolve([item],query),item,`${item.symbol}: ${query}`);
  assert.deepEqual(S.search([item,item],query),[item],'Repeated ticker rows create one suggestion');
 }
 assert.equal(S.search([item],'스카이')[0],item,'Partial name remains searchable');
 for(const label of ['스카이댄스','파라마운트 스카이댄스','Skydance Corporation','Paramount Skydance Corporation'])
  for(const query of [item.symbol+' '+label,label+' '+item.symbol])assert.equal(S.resolve([item],query),item,query);
 assert.equal(S.resolve([item],'파라마운트 글로벌'),null,'Do not infer predecessor aliases');
}
for(const both of [[old,current],[current,old]]){
 for(const query of ['파라마운트','스카이댄스','Paramount Skydance Corporation','Skydance Corporation']){
  assert.deepEqual(S.search(both,query,Infinity).map(row=>row.symbol),['PSKY','SKYD']);
  assert.equal(S.resolve(both,query),null,'Shared names require an explicit data-row selection');
 }
 assert.equal(S.resolve(both,'PSKY'),old,'Exact available ticker outranks its alias');
 assert.equal(S.resolve(both,'SKYD'),current);
 assert.equal(S.resolve(both,'스카이댄스 SKYD'),current);
 assert.equal(S.resolve(both,'Skydance Corporation PSKY'),old);
}
for(const query of aliases)assert.deepEqual(S.search([{symbol:'AAPL'}],query),[],'Aliases cannot invent unavailable rows');
assert.equal(S.resolve([{symbol:'SKYDW',name:'Skydance warrants'}],'PSKY'),null,'Warrants are a separate security');
assert.equal(S.resolve([{symbol:'WBD',name:'Warner Bros. Discovery'}],'SKYD'),null,'Cash-merger membership is not a ticker rename');
assert.deepEqual(S.search([current],'WBD'),[]);
const catalog=require('../assets/company-names.js');
assert(!catalog.SKYD.includes('PARA'),'Prior merger tickers are not registered as security aliases');
const predecessor={symbol:'PARA',name:'Paramount Global'};
assert.equal(S.resolve([current,predecessor],'PARA'),predecessor,'Exact predecessor ticker outranks partial Paramount text');
assert(Object.isFrozen(catalog)&&Object.isFrozen(catalog.PSKY)&&Object.isFrozen(catalog.SKYD));
// Browser UMD path uses the same catalog and semantics as Node.
const browser={};
for(const path of ['assets/company-names.js','assets/company-search.js'])
 require('node:vm').runInNewContext(fs.readFileSync(path,'utf8'),browser);
assert.equal(browser.CompanySearch.resolve([current],'Skydance Corporation'),current);
assert.equal(browser.CompanySearch.resolve([old],'SKYD'),old);
// The combobox selects the actual available key, not the alias the user typed.
function combobox(rows){
 function element(){return {children:[],events:{},attrs:{},hidden:true,value:'',textContent:'',
  addEventListener(type,fn){this.events[type]=fn},setAttribute(key,value){this.attrs[key]=value},
  removeAttribute(key){delete this.attrs[key]},append(...children){this.children.push(...children)},
  replaceChildren(){this.children=[]},scrollIntoView(){},blur(){},select(){}};}
 const input=element(),menu=element(),options=element(),status=element(),selected=[];
 options.id='company-options';input.ownerDocument={createElement:element};
 const nodes={'[data-company-menu]':menu,'[data-company-options]':options,'[data-company-status]':status};
 S.mount({input,host:{querySelector:key=>nodes[key]},items:rows,onSelect:key=>selected.push(key)});
 return {input,menu,options,status,selected,query(value){input.value=value;input.events.input({});},
  key(value){input.events.keydown({key:value,preventDefault(){}});}};
}
for(const [rows,query,key,label] of [[[current],'PSKY','SKYD','스카이댄스'],[[old],'SKYD','PSKY','파라마운트 스카이댄스']]){
 const box=combobox(rows);box.query(query);
 assert.equal(box.options.children.length,1);assert.equal(box.options.children[0].children[0].textContent,label);
 box.key('Enter');assert.deepEqual(box.selected,[key]);assert.equal(box.input.value,label+' · '+key);assert(box.menu.hidden);
}
const ambiguousBox=combobox([old,current]);ambiguousBox.query('스카이댄스');ambiguousBox.key('Enter');
assert.deepEqual(ambiguousBox.selected,[]);assert.equal(ambiguousBox.options.children.length,2);
ambiguousBox.key('ArrowDown');ambiguousBox.key('Enter');assert.deepEqual(ambiguousBox.selected,['PSKY']);
assert.equal(JSON.stringify([old,current]),JSON.stringify([{symbol:'PSKY',name:'Paramount Skydance Corporation'},{symbol:'SKYD',name:'Paramount Skydance Corporation'}]));
// A financial merge/export keeps dated keys, source names, prices and EPS apart.
const historicalPrices=[{symbol:'PSKY',yahooSymbol:'SKYD',close:'9.53',date:'2026-10-06'},
 {symbol:'SKYD',yahooSymbol:'SKYD',close:'9.27',date:'2026-10-13'}];
const historicalFunds=[{symbol:'PSKY',shortName:old.name,forwardEps:'1'},
 {symbol:'SKYD',shortName:current.name,forwardEps:'2'}];
const original=JSON.stringify([historicalPrices,historicalFunds]);
const historyRows=E.merge(historicalPrices,historicalFunds);
assert.equal(historyRows.length,2,'Search aliases must not merge financial identities');
for(const [key,price,date,eps,label] of [['PSKY',9.53,'2026-10-06',1,'파라마운트 스카이댄스'],['SKYD',9.27,'2026-10-13',2,'스카이댄스']]){
 const row=historyRows.find(row=>row.symbol===key);
 assert.equal(row.price,price);assert.equal(row.priceAt,date);assert.equal(row.eps,eps);assert.equal(row.nameKo,label);
 assert.equal(row.name,current.name);
 for(const query of ['PSKY','SKYD','스카이댄스','Skydance Corporation'])assert.equal(E.filter([row],{search:query})[0],row);
 const exported=E.csv(E.exportCSV([row]))[0];
 assert.equal(exported.symbol,key);assert.equal(exported.name,current.name);assert.equal(exported.nameKo,label);
 assert.equal(Number(exported.price),price);assert.equal(Number(exported.eps),eps);
}
assert.equal(JSON.stringify([historicalPrices,historicalFunds]),original,'Keep historical/source records unchanged');
// Verify the real snapshot also searches both names while retaining its source ticker.
const sourceItem=items.find(row=>row.symbol==='SKYD')||items.find(row=>row.symbol==='PSKY');
assert(sourceItem,'Expected the Paramount/Skydance security in this snapshot');
for(const query of ['PSKY','SKYD','스카이댄스','파라마운트','Skydance Corporation','Paramount Skydance Corporation'])
 assert.equal(S.resolve(items,query),sourceItem,`Live snapshot: ${query}`);
console.log('Company search: '+items.length+' company labels, Korean/English/ticker aliases, PSKY/SKYD source-name changes, duplicate/ambiguous rows, historical keys, browser catalog and screener/CSV integration passed.');
