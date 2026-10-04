'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const H=require('../assets/market-home.js'),R=require('./build_home_rankings.cjs');
const A=require('../assets/stock-assessment.js');
const now=Date.parse('2026-10-03T23:00:00Z');
const a=(symbol,score,code,holding='hold')=>({symbol,score,asOf:'2026-10-02',plan:{code,holding:{code:holding}}});
const inputs={Z:a('Z',100,'watch'),B:a('B',90,'buy'),A:a('A',90,'buy'),C:a('C',80,'buy'),D:a('D',70,'buy'),P:a('P',0,'avoid','protect'),Y:a('Y',2,'avoid','reduce'),X:a('X',2,'avoid','reduce'),S:a('S',5,'confirm','reduce'),N:a('N',null,'buy','reduce')};
assert.deepEqual(R.select(inputs).buy.map(q=>q.symbol),['A','B','C']);
assert.deepEqual(R.select(inputs).sell.map(q=>q.symbol),['X','Y','S']);
assert.equal(R.select({Z:inputs.Z}).buy.length,0);
assert.equal(R.select({B:inputs.B}).buy.length,1);
const waitingInputs={
  Z:a('Z',90,'breakout'),A:a('A',90,'pullback'),R:a('R',80,'riskwait'),D:a('D',70,'breakout'),
  AVOID:a('AVOID',100,'avoid'),MISSING:a('MISSING',100,'unavailable'),HOT:a('HOT',100,'overextended'),
  SUPPORT:a('SUPPORT',100,'confirm'),WATCH:a('WATCH',100,'watch'),INVALID:a('INVALID',null,'pullback')
};
const waitingBefore=JSON.stringify(waitingInputs),selected=R.select(waitingInputs);
assert.deepEqual(selected.buy,[],'Waiting states must never become actual buys');
assert.deepEqual(selected.waiting.map(q=>[q.symbol,q.code]),[['A','pullback'],['Z','breakout'],['R','riskwait']]);
assert.equal(JSON.stringify(waitingInputs),waitingBefore,'Selection must preserve the original assessments');
assert.deepEqual(R.select({...waitingInputs,B:inputs.B}).buy,[{symbol:'B',name:'B',asOf:'2026-10-02'}]);
assert.deepEqual(R.select({...waitingInputs,B:inputs.B}).waiting,[],'One actual buy suppresses every waiting candidate without padding TOP 3');
assert.deepEqual(R.select({}).waiting,[]);
const rankings={...selected,marketGeneratedAt:'2026-10-03T22:00:00Z',marketMaxAgeDays:3};
const waitHtml=H.buyHtml(rankings,now);
assert(waitHtml.includes('현재 매수 후보 없음')&&waitHtml.includes('진입 대기 후보'));
assert(waitHtml.includes('매수 조건 충족 전'));
for(const label of ['돌파 대기','눌림목 대기','위험 조절 대기'])assert(waitHtml.includes(label));
assert.equal((waitHtml.match(/class="hp-pick hp-wait-pick"/g)||[]).length,3);
assert(!waitHtml.includes('hp-rank"'),'Waiting candidates are separate from the numbered buy TOP');
assert.equal(H.buyHtml({...rankings,buy:[{symbol:'B',name:'B',asOf:'2026-10-02'}]},now),H.rankingHtml([{symbol:'B',name:'B',asOf:'2026-10-02'}],'buy',now));
assert.equal(H.buyHtml({...rankings,buy:[{symbol:'B',asOf:'2026-09-20'}]},now),H.rankingHtml([{symbol:'B',asOf:'2026-09-20'}],'buy',now),'Expired buy rows must not be replaced with waiting states');
for(const marketGeneratedAt of [undefined,'invalid','2026-10-03T23:01:00Z','2026-09-29T22:00:00Z']){
  for(const buy of [[],[{symbol:'B',asOf:'2026-10-02'}]])assert.equal(H.buyHtml({...rankings,buy,marketGeneratedAt},now),'<p class="hp-muted">시장 자료 갱신 대기</p>');
}
assert(H.buyHtml({...rankings,marketGeneratedAt:new Date(now-3*86400000).toISOString()},now).includes('진입 대기 후보'));
assert(!H.buyHtml({...rankings,marketGeneratedAt:new Date(now-3*86400000-1).toISOString()},now).includes('진입 대기 후보'));
for(const waiting of [undefined,[],[{symbol:'X',asOf:'2026-10-02',code:'avoid'}]])assert.equal(H.buyHtml({...rankings,waiting},now),H.rankingHtml([],'buy',now));
const invalidWaiting=[null,...['avoid','unavailable','overextended','confirm','watch','buy','toString','__proto__'].map(code=>({symbol:'X',asOf:'2026-10-02',code})),
  {symbol:'<script>',asOf:'2026-10-02',code:'breakout'},
  {symbol:'OLD',asOf:'2026-09-20',code:'pullback'},
  {symbol:'FUTURE',asOf:'2026-10-04',code:'riskwait'}];
assert.deepEqual(H.waitingRows([...invalidWaiting,...selected.waiting,{symbol:'EXTRA',asOf:'2026-10-02',code:'breakout'}],now),selected.waiting);
assert(H.buyHtml({...rankings,waiting:[{symbol:'BRK.B',name:'<script>',asOf:'2026-10-02',code:'breakout'}]},now).includes('&lt;script&gt;'));

// Exercise the real technical plan and file builder: a waiting close, an actual
// breakout entry, then stale market data with the same fresh price history.
const day='2026-10-02',market={generatedAt:day+'T22:00:00Z',credit:{status:'stable'},indicators:['NFCI','STLFSI4','DRTSCILM','FUNDING'].map(id=>({id,status:'ready',asOf:day,maxAgeDays:5}))};
const stock=price=>({symbol:'TEST',status:'ready',fresh:true,asOf:day,price,
  history:Array.from({length:260},(_,i)=>({date:new Date(Date.parse(day)-(259-i)*86400000).toISOString().slice(0,10),close:i===259?price:90+i*.036+Math.sin(i*.3)*.25,volume:1000})),
  inputs:{ma20:100,ma50:95,ma200:90,return1m:.04,return3m:.12,volatility4m:.2}});
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'home-rankings-'));
try{
  for(const name of ['forecasts','market'])fs.mkdirSync(path.join(dir,name));
  const write=(price,m)=>{
    fs.writeFileSync(path.join(dir,'forecasts/latest.json'),JSON.stringify({generatedAt:day+'T22:00:00Z',stocks:{TEST:stock(price)}}));
    fs.writeFileSync(path.join(dir,'market/latest.json'),JSON.stringify(m));
    return R.build(dir,now);
  };
  const beforeEntry=write(99.2,market);
  assert.equal(A.evaluate(stock(99.2),market,null,126,now).plan.code,'breakout');
  assert.deepEqual(beforeEntry.buy,[]);assert.equal(beforeEntry.waiting[0].code,'breakout');
  const entry=write(100,market);
  assert.equal(A.evaluate(stock(100),market,null,126,now).plan.code,'buy');
  assert.equal(entry.buy[0].symbol,'TEST');assert.deepEqual(entry.waiting,[]);
  const staleMarket={...market,generatedAt:'2026-09-29T22:00:00Z'};
  for(const price of [99.2,100]){
    const stale=write(price,staleMarket);
    assert.deepEqual(stale.buy,[]);assert.deepEqual(stale.waiting,[]);
    assert.equal(stale.marketGeneratedAt,staleMarket.generatedAt);
    assert(!H.buyHtml(stale,now).includes('hp-pick'));
  }
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
console.log('Home: strict buy TOP, separate waiting states, actual entry priority, stale market/price suppression, Monday-Friday periods, breaking expiry, safe summaries and equal chart scales passed.');
