(function(root){
'use strict';
const DAY=86400000,esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const normalize=x=>String(x||'').trim().toUpperCase().replace(/\./g,'-');
let data=null,loading=null,failed=false,loadedAt=0,sequence=0;
let newsData=null,newsFailed=false;
function dateMs(value){
 if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return NaN;
 const ms=Date.parse(value+'T00:00:00Z');return Number.isFinite(ms)&&new Date(ms).toISOString().slice(0,10)===value?ms:NaN;
}
function observed(value,now){const ms=Date.parse(value);return Number.isFinite(ms)&&ms<=now?ms:NaN}
function safeSource(value,upcoming=false){
 try{const u=new URL(value);if(u.protocol!=='https:'||u.username||u.password||u.port)return false;
  if(upcoming)return u.hostname==='finance.yahoo.com'&&/^\/quote\/[A-Z0-9.-]+\/calendar\/$/.test(u.pathname);
  return u.hostname==='www.sec.gov'&&/^\/Archives\/edgar\/data\/\d+\/\d{18}\/[A-Za-z0-9_.-]+\.(htm|html|txt)$/i.test(u.pathname)||
   u.hostname==='nvidianews.nvidia.com'&&u.pathname.startsWith('/news/')||
   u.hostname==='www.microsoft.com'&&/^\/en-us\/Investor\/earnings\//i.test(u.pathname);
 }catch(_){return false}
}
function select(snapshot,ticker,now=Date.now()){
 const key=normalize(ticker),issuer=snapshot?.schemaVersion===1?snapshot.issuers?.[snapshot.symbols?.[key]]:null;
 const today=Math.floor(now/DAY)*DAY;
 const valid=(e,planned=false)=>{
  const d=dateMs(e?.date),seen=observed(e?.observedAt,now);
  return Number.isFinite(d)&&Number.isFinite(seen)&&safeSource(e?.source?.url,planned)&&
   typeof e.title==='string'&&(planned?e.dateKind==='estimated'&&d>=today&&d<=today+120*DAY&&now-seen<=8*DAY:
    ['filed','published'].includes(e.dateKind)&&d<=today&&d>=today-180*DAY&&d<=Math.floor(seen/DAY)*DAY);
 };
 const past=[...new Map((Array.isArray(issuer?.events)?issuer.events:[]).filter(e=>valid(e)).map(e=>[e.id,e])).values()]
  .sort((a,b)=>b.date.localeCompare(a.date)||String(a.id).localeCompare(String(b.id))).slice(0,20);
 const calendar=snapshot?.upcoming?.[key];
 const upcoming=(issuer&&Array.isArray(calendar)?calendar:[]).filter(e=>valid(e,true)).sort((a,b)=>a.date.localeCompare(b.date)).slice(0,2);
 const success=observed(issuer?.sec?.lastSuccessAt,now),fresh=Number.isFinite(success)&&now-success<=4*DAY;
 return {key,issuer,past,upcoming,fresh:issuer?.sec?.status==='ready'&&fresh,checkedAt:Number.isFinite(success)?issuer.sec.lastSuccessAt:null,today};
}
function confirmed(value){return value?esc(value.replace('T',' ').slice(0,19))+' UTC':'미확인'}
const impacts={positive:'호재',negative:'악재',mixed:'혼재',neutral:'중립',unclear:'판단 유보'};
function safeNewsSource(value){
 try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&
  /^(?:[a-z0-9][a-z0-9-]*\.)+[a-z]{2,63}$/.test(u.hostname)&&!/(?:\.localhost|\.local|\.internal|\.example|\.test)$/.test(u.hostname);
 }catch(_){return false}
}
function newsTime(value,now){
 return typeof value==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(dateMs(value.slice(0,10)))?observed(value,now):NaN;
}
function selectNews(snapshot,ticker,now=Date.now()){
 const key=normalize(ticker),issuer=snapshot?.schemaVersion===1?snapshot.issuers?.[snapshot.symbols?.[key]]:null;
 const rows=(Array.isArray(issuer?.articles)?issuer.articles:[]).filter(e=>{
  const published=newsTime(e?.publishedAt,now),seen=newsTime(e?.observedAt,now);
  return typeof e?.id==='string'&&typeof e.title==='string'&&safeNewsSource(e?.source?.url)&&
   Number.isFinite(published)&&Number.isFinite(seen)&&published<=seen&&now-published<=30*DAY;
 }).sort((a,b)=>b.publishedAt.localeCompare(a.publishedAt)||a.id.localeCompare(b.id));
 const articles=[...new Map(rows.map(e=>[e.id,e])).values()].slice(0,12);
 const success=newsTime(issuer?.feed?.lastSuccessAt,now),sourceFresh=Number.isFinite(success)&&now-success<=2*DAY,fresh=issuer?.feed?.status==='ready'&&sourceFresh;
 const counts=Object.fromEntries(Object.keys(impacts).map(k=>[k,0]));
 const validImpact=e=>e?.impact?.classifier==='company-impact-headline-v1'&&e.impact.basis==='headline'&&Object.hasOwn(impacts,e.impact.status)&&typeof e.impact.reason==='string';
 for(const e of articles)counts[validImpact(e)?e.impact.status:'unclear']++;
 return {key,issuer,articles,fresh,sourceFresh,checkedAt:Number.isFinite(success)?issuer.feed.lastSuccessAt:null,counts,validImpact};
}
function newsCard(e,s){
 const impact=s.validImpact(e)?e.impact:{status:'unclear',reason:'판단 근거가 없어 원문 확인이 필요합니다.'};
 const topics=Array.isArray(impact.topics)?impact.topics.filter(x=>typeof x==='string'):[],evidence=Array.isArray(impact.evidence)?impact.evidence.filter(x=>typeof x==='string'):[];
 return '<li class="ce-news-card"><div class="ce-news-meta"><span class="ce-impact ce-'+impact.status+'">'+impacts[impact.status]+'</span><span>'+esc(topics.slice(0,2).join(' · '))+'</span><time datetime="'+esc(e.publishedAt)+'">'+esc(e.publishedAt.slice(0,10))+'</time></div><a class="ce-news-title" href="'+esc(e.source.url)+'" target="_blank" rel="noopener noreferrer">'+esc(e.title)+'</a><p class="ce-news-reason">'+esc(impact.reason)+'</p><div class="ce-news-source">'+esc(e.source.name||'기사 원문')+' · 발행일 UTC</div><details class="ce-news-detail"><summary>제공 요약·판단 근거</summary>'+(typeof e.summary==='string'&&e.summary?'<p>'+esc(e.summary)+'</p>':'<p>제공 요약이 없습니다.</p>')+(evidence.length?'<p>제목에서 확인한 표현: '+esc(evidence.slice(0,3).join(' · '))+'</p>':'')+'<small>제목 기반 예비 판단 · 확인 '+confirmed(e.observedAt)+'</small></details></li>';
}
function newsPanel(ticker,snapshot=newsData,now=Date.now()){
 const s=selectNews(snapshot,ticker,now);
 const state=s.fresh?'최근 뉴스 확인':s.checkedAt?'마지막 확보 뉴스':newsFailed?'뉴스 읽기 실패':snapshot?'뉴스 수집 대기':'뉴스 확인 중';
 let content=s.articles.length?'<div class="ce-news-counts" aria-label="표시된 기사별 분류">'+Object.entries(impacts).map(([key,label])=>'<span class="ce-count ce-'+key+'">'+label+' <b>'+s.counts[key]+'</b></span>').join('')+'</div><p class="ce-news-scope">최근 30일 중 확보한 기사 '+s.articles.length+'개 · 최신순</p><ol class="ce-news-list">'+s.articles.slice(0,4).map(e=>newsCard(e,s)).join('')+'</ol>':'<p class="ce-empty">'+(s.fresh?'확인한 뉴스 피드에 최근 표시할 회사 기사가 없습니다.':'최근 회사 뉴스 확인 자료가 없습니다.')+' 뉴스가 없거나 영향이 중립이라는 뜻은 아닙니다.</p>';
 if(s.articles.length>4)content+='<details class="ce-more"><summary>회사 뉴스 '+(s.articles.length-4)+'개 더 보기</summary><ol class="ce-news-list">'+s.articles.slice(4).map(e=>newsCard(e,s)).join('')+'</ol></details>';
 return '<div class="ce-heading"><div><small>COMPANY NEWS · '+esc(s.key)+'</small><h3>회사 뉴스 · 호재와 악재</h3></div><span class="ce-status ce-news-status'+(s.fresh?' ce-ready':'')+'">'+state+'</span></div>'+(s.checkedAt?'<p class="ce-collection">'+(s.fresh?'뉴스 확인 ':s.sourceFresh?'마지막 원문 확보 ':'수집 지연 · 마지막 뉴스 확인 ')+confirmed(s.checkedAt)+'</p>':'')+content+'<p class="ce-news-note">호재·악재는 제목에서 확인한 내용의 예비 판단입니다. 유리한 소식과 부담 요인이 함께 있으면 혼재, 근거가 부족하면 판단 유보로 표시합니다. 실제 주가 방향·매수 신호와는 다를 수 있습니다.</p>';
}
const categories={earnings:'실적',report:'보고서',contract:'계약',corporate:'기업 변화',capital:'자금·주식',governance:'지배구조',security:'보안',disclosure:'공시'};
function card(e,today){
 const planned=e.dateKind==='estimated',type=planned?'예상 일정':categories[e.category]||'공시';
 const remaining=Math.round((dateMs(e.date)-today)/DAY),label=planned?(remaining===0?'오늘 예정':'D−'+remaining):e.dateKind==='filed'?'공시일':'발표일';
 const fields=(Array.isArray(e.details)?e.details:[]).filter(x=>x&&typeof x.label==='string'&&typeof x.value==='string').slice(0,6);
 if(e.reportDate&&Number.isFinite(dateMs(e.reportDate)))fields.unshift({label:e.form?.startsWith('8-K')?'공시상 기준일':'보고 대상 기간 종료',value:e.reportDate});
 return '<li><details class="ce-event'+(planned?' ce-upcoming':'')+'"><summary><time datetime="'+esc(e.date)+'"><b>'+esc(e.date.slice(5).replace('-','.'))+'</b><span>'+esc(e.date.slice(0,4))+'</span><small>'+esc(label)+'</small></time><div class="ce-card-heading"><span class="ce-tag ce-'+(planned?'estimate':esc(Object.hasOwn(categories,e.category)?e.category:'disclosure'))+'">'+esc(type)+'</span><strong>'+esc(e.title)+'</strong><small>'+esc(e.form||e.source.name)+'</small></div><span class="ce-expand" aria-hidden="true">+</span></summary><div class="ce-body"><p>'+esc(e.summary||'상세 내용은 원문에서 확인하세요.')+'</p>'+(fields.length?'<dl>'+fields.map(x=>'<div><dt>'+esc(x.label)+'</dt><dd>'+esc(x.value)+'</dd></div>').join('')+'</dl>':'')+(e.form?.startsWith('8-K')?'<small>공시일은 사건 발생일·실적 발표일과 다를 수 있습니다. '+(e.items?.length?'공시 항목 '+esc(e.items.join(', '))+'. ':'')+'구체적인 조건과 내용은 원문을 확인하세요.</small>':'')+'<div class="ce-source"><a href="'+esc(e.source.url)+'" target="_blank" rel="noopener noreferrer">'+esc(e.source.name)+' 원문 ↗</a><small>확인 '+confirmed(e.observedAt)+'</small></div></div></details></li>';
}
function panel(ticker,snapshot=data,now=Date.now(),newsSnapshot=newsData){
 const s=select(snapshot,ticker,now),list=rows=>'<ol class="ce-list">'+rows.map(e=>card(e,s.today)).join('')+'</ol>';
 const state=s.fresh?'최근 공시 확인':s.checkedAt?'마지막 확보 자료':s.past.length?'회사 발표 연결':failed?'자료 읽기 실패':snapshot?'공시 수집 대기':'자료 확인 중';
 let content='<h4>다가오는 일정</h4>'+(s.upcoming.length?list(s.upcoming):'<p class="ce-empty">최신 예정 일정 확인 자료가 없습니다.</p>')+'<h4>최근 180일</h4>';
 content+=s.past.length?list(s.past.slice(0,4)):'<p class="ce-empty">'+(s.fresh?'확인한 공시 범위에 최근 표시할 항목이 없습니다.':'최근 공시 확인 자료가 없습니다. 원문으로 확인하세요.')+'</p>';
 if(s.past.length>4)content+='<details class="ce-more"><summary>이전 공시 '+(s.past.length-4)+'개 더 보기</summary>'+list(s.past.slice(4))+'</details>';
 const cik=s.issuer?.cik,edgar=Number.isInteger(cik)&&cik>0?'<a href="https://www.sec.gov/edgar/browse/?CIK='+cik+'&owner=exclude" target="_blank" rel="noopener noreferrer">SEC 전체 공시 ↗</a>':'';
 return '<section class="company-events" data-event-symbol="'+esc(s.key)+'" aria-label="'+esc(s.key)+' 회사 뉴스">'+newsPanel(ticker,newsSnapshot,now)+'<details class="ce-filings"><summary>공시·일정 보조 자료</summary><div class="ce-heading"><h3>공시·일정</h3><span class="ce-status'+(s.fresh?' ce-ready':'')+'">'+state+'</span></div>'+(!s.fresh&&s.checkedAt?'<p class="ce-collection">수집 지연 · 마지막 공시 확인 '+confirmed(s.checkedAt)+'</p>':'')+content+'<footer>'+edgar+'<details><summary>출처·수집 범위</summary><p>SEC 주요 사항·정기 보고서·주주총회 자료를 공시일 순으로 표시합니다. 회사 원문 실적 요약은 NVDA·MSFT에 연결되어 있습니다. 예상 실적일은 Yahoo 제공 자료로, 회사 확정 일정과 구분합니다.</p><p>SEC 확인 '+confirmed(s.checkedAt)+'. 수집 누락은 사건이 없다는 뜻이 아닙니다. 공시 종류만으로 호재·악재를 판단하지 않습니다.</p></details></footer></details></section>';
}
async function load(fetcher=root.fetch?.bind(root),force=false){
 const age=Date.now()-loadedAt;
 if(loading&&!force&&!failed&&!newsFailed&&age>=0&&age<60000)return loading;
 const version=++sequence;loadedAt=Date.now();
 loading=(async()=>{await Promise.all([
  (async()=>{try{const r=await fetcher('events/latest.json',{cache:'no-store'});if(!r.ok)throw Error('events');const x=await r.json();if(x?.schemaVersion!==1||!x.issuers||!x.symbols)throw Error('schema');if(version===sequence){data=x;failed=false}}catch(_){if(version===sequence){data=null;failed=true}}})(),
  (async()=>{try{const r=await fetcher('news/latest.json',{cache:'no-store'});if(!r.ok)throw Error('news');const x=await r.json();if(x?.schemaVersion!==1||x.classifierVersion!=='company-impact-headline-v1'||!x.issuers||!x.symbols)throw Error('schema');if(version===sequence){newsData=x;newsFailed=false}}catch(_){if(version===sequence){newsData=null;newsFailed=true}}})()
 ]);return data})();
 return loading;
}
function mount(host,ticker){
 if(!host)return;const key=normalize(ticker);host.dataset.eventSymbol=key;host.innerHTML=panel(key);
 load().then(()=>{if(host.isConnected&&host.dataset.eventSymbol===key)host.innerHTML=panel(key)});
}
const api={load,panel,select,mount,safeSource,newsPanel,selectNews,safeNewsSource};if(typeof module!=='undefined')module.exports=api;else root.CompanyEvents=api;
})(typeof window!=='undefined'?window:globalThis);
