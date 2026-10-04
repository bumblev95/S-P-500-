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
console.log('Company search: '+items.length+' company labels, Korean/English/ticker aliases, ambiguity, availability, class tickers and screener/CSV integration passed.');
