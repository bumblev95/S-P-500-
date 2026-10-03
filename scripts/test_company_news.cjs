const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const C=require('../assets/company-events.js'),now=Date.parse('2026-10-03T03:00:00Z');
const article={id:'news:one',title:'Nvidia raises revenue outlook',summary:'Supplied excerpt',
 publishedAt:'2026-10-02T22:00:00+00:00',observedAt:'2026-10-03T02:00:00+00:00',
 source:{name:'Yahoo Finance',url:'https://finance.yahoo.com/news/nvidia-update.html'},
 impact:{classifier:'company-impact-source-v2',basis:'headline-and-excerpt',status:'positive',reason:'회사의 실적 전망 상향은 수익 기대에 유리합니다.',topics:['전망 상향'],evidence:['raises revenue outlook'],kind:'company'}};
article.ko={version:'company-news-ko-v5',language:'ko',status:'ready',summary:'엔비디아가 매출 전망을 상향했습니다.',sourceTitle:article.title,sourceExcerpt:article.summary};
const fixture={schemaVersion:1,classifierVersion:'company-impact-source-v2',symbols:{NVDA:'1045810','NVDA-B':'1045810'},
 issuers:{1045810:{cik:1045810,feed:{status:'ready',lastSuccessAt:article.observedAt},articles:[article]}}};
const events={schemaVersion:1,symbols:fixture.symbols,issuers:{1045810:{cik:1045810,sec:{status:'ready',lastSuccessAt:article.observedAt},events:[]}},upcoming:{}};
let s=C.selectNews(fixture,'nvda.b',now);assert(s.fresh);assert.equal(s.counts.positive,1);assert.equal(s.articles[0].id,article.id);
let html=C.panel('NVDA',events,now,fixture);assert(html.indexOf('회사 뉴스 · 호재와 악재')<html.indexOf('공시·일정 보조 자료'));
assert(html.includes('호재'));assert.equal(C.koreanSummary(article),article.ko.summary);assert(html.includes('엔비디아가 매출 전망을 상향했습니다.'));assert(html.includes(article.impact.reason));assert(html.includes('noopener noreferrer'));assert(html.includes('예비 판단'));
assert.equal(C.selectNews(fixture,'MISSING',now).articles.length,0);
assert(C.newsPanel('MISSING',fixture,now).includes('중립이라는 뜻은 아닙니다'));
assert(!C.selectNews(fixture,'NVDA',now+3*86400000).fresh);
const captured=structuredClone(fixture);captured.issuers[1045810].feed.status='captured';
assert(!C.selectNews(captured,'NVDA',now).fresh);
assert(C.selectNews(captured,'NVDA',now).sourceFresh);
assert(C.newsPanel('NVDA',captured,now).includes('마지막 원문 확보'));
assert(!C.newsPanel('NVDA',captured,now).includes('수집 지연'));
assert(!C.selectNews(fixture,'NVDA',now+31*86400000).articles.length);
assert(!C.selectNews(fixture,'NVDA',now-86400000).articles.length);
for(const change of [{publishedAt:'2026-10-04T00:00:00Z'},{publishedAt:'2026-09-31T00:00:00Z'},
 {publishedAt:'2026-10-02'},{observedAt:'2026-10-01T00:00:00Z'},
 {source:{url:'javascript:alert(1)'}},{source:{url:'https://user@finance.yahoo.com/news/test'}},
 {source:{url:'https://127.0.0.1/private'}}]){
 const bad=structuredClone(fixture);bad.issuers[1045810].articles=[{...article,...change}];
 assert.equal(C.selectNews(bad,'NVDA',now).articles.length,0);
}
const ordering=structuredClone(fixture);ordering.issuers[1045810].articles=[{...article,id:'opinion',publishedAt:'2026-10-03T01:00:00Z',impact:{...article.impact,status:'unclear',kind:'market'}},{...article,id:'rating',impact:{...article.impact,kind:'analyst'}},article];
assert.equal(C.selectNews(ordering,'NVDA',now).primary[0].id,article.id);assert.equal(C.selectNews(ordering,'NVDA',now).reference[0].id,'opinion');
assert(C.newsPanel('NVDA',ordering,now).includes('참고 뉴스·회사 공지 1개 보기'));
const changed=structuredClone(article);changed.title+=' changed';assert.equal(C.koreanSummary(changed),null);changed.title=article.title;changed.summary+=' changed';assert.equal(C.koreanSummary(changed),null);
const poisoned=structuredClone(fixture);poisoned.issuers[1045810].articles[0].title='<img src=x onerror=alert(1)>';
poisoned.issuers[1045810].articles[0].impact.reason='<script>alert(1)</script>';
html=C.newsPanel('NVDA',poisoned,now);assert(!html.includes('<script'));assert(!html.includes('<img'));assert(html.includes('&lt;img'));
const corrupt=structuredClone(fixture);corrupt.issuers[1045810].articles[0].impact={status:'positive',reason:'no provenance',topics:{}};
assert.equal(C.selectNews(corrupt,'NVDA',now).counts.unclear,1);assert(C.newsPanel('NVDA',corrupt,now).includes('추가 확인'));
corrupt.issuers[1045810].articles[0].impact={...article.impact,topics:{},evidence:{}};assert.doesNotThrow(()=>C.newsPanel('NVDA',corrupt,now));
for(const file of ['index.html','advanced.html','advanced-legacy.html']){
 const text=fs.readFileSync(file,'utf8');assert(text.includes('company-events.js?v=4'));assert(text.includes('company-events.css?v=3'));
}
(async()=>{
 let clockNow=now,releases=[],reads=[];const root={};
 vm.runInNewContext(fs.readFileSync('assets/company-events.js','utf8'),{window:root,Date:class extends Date{static now(){return clockNow}},URL});
 const api=root.CompanyEvents;
 const fetcher=async url=>{reads.push(url);return {ok:true,json:async()=>url.startsWith('news/')?fixture:events}};
 await api.load(fetcher);assert.equal(reads.length,2);assert(api.panel('NVDA').includes(article.title));
 await api.load(fetcher);assert.equal(reads.length,2);
 clockNow+=61000;await api.load(fetcher);assert.equal(reads.length,4);
 await api.load(async url=>url.startsWith('news/')?{ok:false}:{ok:true,json:async()=>events},true);
 assert(api.panel('NVDA').includes('뉴스 읽기 실패'));assert(api.panel('NVDA').includes('최근 공시 확인'));
 await api.load(fetcher);assert(api.panel('NVDA').includes(article.title));
 await api.load(async url=>url.startsWith('events/')?{ok:false}:{ok:true,json:async()=>fixture},true);
 assert(api.panel('NVDA').includes(article.title));assert(api.panel('NVDA').includes('자료 읽기 실패'));
 const older=api.load(()=>new Promise(resolve=>releases.push(resolve)),true);
 await api.load(async url=>({ok:true,json:async()=>url.startsWith('news/')?{...fixture,issuers:{1045810:{...fixture.issuers[1045810],articles:[]}}}:events}),true);
 releases.forEach((release,i)=>release({ok:true,json:async()=>i===0?events:fixture}));await older;
 assert(!api.panel('NVDA').includes(article.title),'Older refresh must not overwrite newer news');
 let replies=[];const pending=api.load(()=>new Promise(resolve=>replies.push(resolve)),true);
 const host={dataset:{},innerHTML:'',isConnected:true};api.mount(host,'NVDA');api.mount(host,'NVDA.B');
 replies.forEach((release,i)=>release({ok:true,json:async()=>i===0?events:fixture}));await pending;await Promise.resolve();
 assert(host.innerHTML.includes('data-event-symbol="NVDA-B"'));assert(!host.innerHTML.includes('data-event-symbol="NVDA"'));
 console.log('Company news: dated relevance, labels/provenance, escaping, freshness, independent errors, retry/cache and selection/refresh races passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
