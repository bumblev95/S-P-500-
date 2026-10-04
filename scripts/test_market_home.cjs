'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const H=require('../assets/market-home.js'),R=require('./build_home_rankings.cjs');
const A=require('../assets/stock-assessment.js');
const now=Date.parse('2026-10-03T23:00:00Z');
const a=(symbol,score,code,holding='hold')=>({symbol,score,price:100,asOf:'2026-10-02',reason:'Original entry reason',
  plan:{code,holding:{code:holding,reason:'Original holding reason'}}});
const pick=rows=>R.select(rows,now);
const inputs={Z:a('Z',100,'watch'),B:a('B',90,'buy'),A:a('A',90,'buy'),C:a('C',80,'buy'),D:a('D',70,'buy'),
  P:a('P',0,'avoid','protect'),Y:a('Y',2,'avoid','reduce'),X:a('X',2,'avoid','reduce'),S:a('S',5,'confirm','reduce'),N:a('N',null,'buy','reduce')};
const before=JSON.stringify(inputs),selected=pick(inputs);
assert.deepEqual(selected.buy.map(q=>q.symbol),['A','B','C']);
assert.deepEqual(selected.sell.map(q=>q.symbol),['X','Y','S']);
assert(selected.buy.every(q=>q.selection==='signal'&&q.code==='buy'));
assert(selected.sell.every(q=>q.selection==='signal'&&q.holdingCode==='reduce'));
assert(!Object.hasOwn(selected,'waiting'));
assert.equal(JSON.stringify(inputs),before,'Ranking must not modify technical assessments');
assert.deepEqual(pick(Object.fromEntries(Object.entries(inputs).reverse())),selected,'Input order must not move tied ranks');

// Empty actual buy/reduce sets still have six distinct, honestly labelled picks.
const relative=Object.fromEntries(['A','B','C','D','E','F'].map((symbol,i)=>[symbol,a(symbol,90-i*10,'watch')]));
const ranked=pick(relative);
assert.deepEqual(ranked.buy.map(q=>q.symbol),['A','B','C']);
assert.deepEqual(ranked.sell.map(q=>q.symbol),['F','E','D']);
assert([...ranked.buy,...ranked.sell].every(q=>q.selection==='relative'));
for(const row of ranked.buy)assert.deepEqual(H.rankingSignal(row,'buy'),{label:'흐름 확인',tone:'caution'});
for(const row of ranked.sell)assert.deepEqual(H.rankingSignal(row,'sell'),{label:'상대 하위',tone:'caution'});
const withOneBuy=pick({...relative,F:a('F',1,'buy')});
assert.equal(withOneBuy.buy.length,3);assert.equal(withOneBuy.sell.length,3);
assert.equal(withOneBuy.buy[0].symbol,'F','Actual buy takes precedence over relative score');
assert.equal(withOneBuy.buy.filter(q=>q.selection==='signal').length,1);
const withOneReduce=pick({...relative,D:a('D',99,'watch','reduce')});
assert.equal(withOneReduce.sell[0].symbol,'D','Actual reduction signal takes precedence over relative score');
assert.equal(withOneReduce.sell.length,3);
assert.equal(new Set([...withOneReduce.buy,...withOneReduce.sell].map(q=>q.symbol)).size,6);
const mixed={Z:a('Z',90,'breakout'),A:a('A',90,'pullback'),R:a('R',100,'riskwait'),D:a('D',70,'breakout'),
  HOT:a('HOT',100,'overextended'),WATCH:a('WATCH',100,'watch'),SUPPORT:a('SUPPORT',100,'confirm')};
assert.deepEqual(pick(mixed).buy.map(q=>q.symbol),['A','Z','D'],'Price setups precede high-scoring risk/extension warnings');
for(const code of ['avoid','unavailable','overextended','riskwait']){
  const rows=Object.fromEntries(Object.entries(relative).map(([symbol,row])=>[symbol,{...row,plan:{...row.plan,code}}]));
  const result=pick(rows);
  assert.equal(result.buy.length,3);assert.equal(result.sell.length,3);
  assert(result.buy.every(q=>q.code===code&&q.selection==='relative'));
  assert(result.buy.every(q=>H.rankingSignal(q,'buy').tone==='caution'),'Market risk must never turn into a positive entry badge');
}

const invalid={NULL:null,NO:a('NO',null,'buy'),NAN:a('NAN',NaN,'buy'),HIGH:a('HIGH',101,'buy'),
  ZERO:{...a('ZERO',100,'buy'),price:0},PRICE:{...a('PRICE',100,'buy'),price:Infinity},
  OLD:{...a('OLD',100,'buy'),asOf:'2026-09-20'},FUTURE:{...a('FUTURE',100,'buy'),asOf:'2026-10-04'},
  BADDATE:{...a('BADDATE',100,'buy'),asOf:'2026-02-30'},
  BADSYMBOL:a('<script>',100,'buy'),NOHOLD:a('NOHOLD',100,'watch','unavailable'),
  BADCODE:a('BADCODE',100,'toString')};
assert.deepEqual(pick({...relative,...invalid}),ranked,'Malformed and stale data cannot pad daily lists');
assert.equal(pick({...relative,OLDER:{...a('OLDER',100,'buy'),asOf:'2026-10-01'}}).eligibleCount,6,'Do not mix closing dates');
assert.equal(pick({'BRK.B':a('BRK.B',80,'watch'),'BRK-B':a('BRK-B',80,'watch')}).eligibleCount,1);
assert.equal(pick({}).buy.length,0);assert.equal(pick({}).sell.length,0);
assert.equal(pick({A:inputs.A}).buy.length,1);
assert.equal(pick({A:inputs.A}).sell.length,0,'Never place the same stock on both sides');

const ranks={...ranked,marketGeneratedAt:'2026-10-03T22:00:00Z',marketMaxAgeDays:3};
const buyHtml=H.buyHtml({...ranks,waiting:[{symbol:'IGNORED',asOf:'2026-10-02',code:'breakout'}]},now);
assert.equal((buyHtml.match(/class="hp-pick"/g)||[]).length,3);
assert(!buyHtml.includes('진입 대기 후보')&&!buyHtml.includes('IGNORED'));
assert(!buyHtml.includes('조건 충족'),'Relative ranks must not claim an actual entry');
assert(H.buyHtml(selected,now).includes('조건 충족'));
for(const marketGeneratedAt of [undefined,'invalid','2026-10-03T23:01:00Z','2026-09-29T22:00:00Z']){
  assert.equal(H.buyHtml({...ranks,marketGeneratedAt},now),buyHtml,'Market staleness must not erase price-relative rankings');
  assert(H.rankingNote({...ranks,marketGeneratedAt},now).includes('시장 자료 갱신 지연'));
}
assert(!H.rankingNote(ranks,now).includes('갱신 지연'));
assert.deepEqual(H.rankRows([null,{symbol:'<script>',asOf:'2026-10-02'},...ranked.buy,...ranked.buy],now),ranked.buy);
assert(H.rankingHtml([{symbol:'BRK.B',name:'<script>',reason:'<img onerror=alert(1)>',asOf:'2026-10-02',code:'breakout'}],'buy',now).includes('&lt;script&gt;'));
assert(!H.buyHtml({buy:[{symbol:'OLD',asOf:'2026-09-20'}]},now).includes('hp-pick'));
assert(H.buyHtml({buy:[]},now).includes('최신 순위 자료 확인 중'));

// Real assessment integration: no trigger, a real trigger, risk and stale market.
const day='2026-10-02',market={generatedAt:day+'T22:00:00Z',credit:{status:'stable'},
  indicators:['NFCI','STLFSI4','DRTSCILM','FUNDING'].map(id=>({id,status:'ready',asOf:day,maxAgeDays:5}))};
const stock=(symbol,price)=>({symbol,status:'ready',fresh:true,asOf:day,price,
  history:Array.from({length:260},(_,i)=>({date:new Date(Date.parse(day)-(259-i)*86400000).toISOString().slice(0,10),
    close:i===259?price:90+i*.036+Math.sin(i*.3)*.25,volume:1000})),
  inputs:{ma20:100,ma50:95,ma200:90,return1m:.04,return3m:.12,volatility4m:.2}});
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'home-rankings-'));
try{
  for(const name of ['forecasts','market'])fs.mkdirSync(path.join(dir,name));
  const write=(price,m)=>{
    fs.writeFileSync(path.join(dir,'forecasts/latest.json'),JSON.stringify({generatedAt:day+'T22:00:00Z',
      stocks:Object.fromEntries(['A','B','C','D','E','F'].map(symbol=>[symbol,stock(symbol,price)]))}));
    fs.writeFileSync(path.join(dir,'market/latest.json'),JSON.stringify(m));return R.build(dir,now);
  };
  const beforeEntry=write(99.2,market);
  assert.equal(A.evaluate(stock('A',99.2),market,null,126,now).plan.code,'breakout');
  assert.equal(beforeEntry.buy.length,3);assert.equal(beforeEntry.sell.length,3);
  assert(beforeEntry.buy.every(q=>q.code==='breakout'&&q.selection==='relative'));
  const entry=write(100,market);
  assert.equal(A.evaluate(stock('A',100),market,null,126,now).plan.code,'buy');
  assert.equal(entry.buy.length,3);assert(entry.buy.every(q=>q.selection==='signal'));
  assert.equal(entry.policy,'daily-top3-v1');assert.equal(entry.basis,'technical-relative-ranking');
  for(const m of [{...market,generatedAt:'2026-09-29T22:00:00Z'},{...market,credit:{status:'risk'}}]){
    const result=write(99.2,m);
    assert.equal(result.buy.length,3);assert.equal(result.sell.length,3);
    assert(result.buy.every(q=>q.code===(m.credit.status==='risk'?'avoid':'unavailable')&&q.selection==='relative'));
  }
  const expired=R.build(dir,now+7*86400000);
  assert.equal(expired.eligibleCount,0);assert.deepEqual(expired.buy,[]);assert.deepEqual(expired.sell,[]);
}finally{fs.rmSync(dir,{recursive:true,force:true});}
assert.deepEqual(H.weekBounds(now),{start:'2026-09-28',end:'2026-10-02'});
assert.equal(H.weekBounds(Date.parse('2026-10-05T02:00:00Z')).start,'2026-09-28');
assert.equal(H.weekBounds(Date.parse('2026-10-05T05:00:00Z')).start,'2026-10-05');
const item={importance:'important',sourceStatus:'ready',fromCache:false,publishedAt:'2026-10-03T22:00:00Z',firstPublishedAt:'2026-10-03T22:00:00Z',translationStatus:'ready',headlineKo:'새 발표',summaryKo:'확인된 발표 요약',url:'https://www.federalreserve.gov/newsevents/pressreleases/test.htm'};
assert(H.breaking(item,now));assert(!H.breaking({...item,fromCache:true},now));
assert(!H.breaking({...item,firstPublishedAt:'2026-10-02T22:00:00Z'},now));
assert(!H.breaking(item,now+2*3600000));
assert.equal(H.eligibleNews([{...item,url:'javascript:alert(1)'}],now).length,0);
assert.equal(H.eligibleNews([{...item,publishedAt:'2026-09-01T22:00:00Z'}],now).length,0);
assert.equal(H.rankRows([{symbol:'A',asOf:'2026-09-20'}],now).length,0);
const recap={asOf:'2026-10-02',weekStart:'2026-09-28',sectors:[{symbol:'XLK',name:'기술',icon:'cpu',asOf:'2026-10-02',status:'ready',day:1.3,week:2.8},{symbol:'XLE',name:'에너지',icon:'fuel',asOf:'2026-10-02',status:'ready',day:-1.1,week:-2.2}]};
assert.equal(H.scale(H.chartRows(recap,now)),3.2);
const html=H.chartHtml(recap,now);
assert(html.includes('hp-fall'));assert(html.includes('hp-rise'));assert(html.includes('width:43.74999999999999%')||html.includes('width:43.75%'));
assert(!html.includes('<table'));assert(!html.includes('>+1.30%<'));
const monday=Date.parse('2026-10-05T13:00:00Z');
assert.equal(H.quoteValues(recap.sectors[0],recap,monday).week,null);
assert.equal(H.quoteValues({...recap.sectors[0],asOf:'2026-10-01'},recap,now).day,null);
assert.equal(H.quoteValues(recap.sectors[0],recap,now+7*86400000).day,null);
assert(!/NaN|Infinity/.test(H.chartHtml({asOf:null,sectors:[]},now)));
assert(H.newsHtml({news:[{...item,headlineKo:'<script>alert(1)</script>'}],feeds:[]},now).includes('&lt;script&gt;'));
console.log('Home: complete daily TOP 3, original signal labels, no overlap, freshness, deterministic ordering, unchanged technical plans, Monday-Friday periods, safe summaries and equal chart scales passed.');
