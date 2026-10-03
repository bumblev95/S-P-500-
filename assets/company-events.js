(function(root){
'use strict';
const DAY=86400000,esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const normalize=x=>String(x||'').trim().toUpperCase().replace(/\./g,'-');
let data=null,loading=null,failed=false;
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
const categories={earnings:'실적',report:'보고서',contract:'계약',corporate:'기업 변화',capital:'자금·주식',governance:'지배구조',security:'보안',disclosure:'공시'};
function card(e,today){
 const planned=e.dateKind==='estimated',type=planned?'예상 일정':categories[e.category]||'공시';
 const remaining=Math.round((dateMs(e.date)-today)/DAY),label=planned?(remaining===0?'오늘 예정':'D−'+remaining):e.dateKind==='filed'?'공시일':'발표일';
 const fields=(Array.isArray(e.details)?e.details:[]).filter(x=>x&&typeof x.label==='string'&&typeof x.value==='string').slice(0,6);
 if(e.reportDate&&Number.isFinite(dateMs(e.reportDate)))fields.unshift({label:e.form?.startsWith('8-K')?'공시상 기준일':'보고 대상 기간 종료',value:e.reportDate});
 return '<li><details class="ce-event'+(planned?' ce-upcoming':'')+'"><summary><time datetime="'+esc(e.date)+'"><b>'+esc(e.date.slice(5).replace('-','.'))+'</b><span>'+esc(e.date.slice(0,4))+'</span><small>'+esc(label)+'</small></time><div class="ce-card-heading"><span class="ce-tag ce-'+(planned?'estimate':esc(Object.hasOwn(categories,e.category)?e.category:'disclosure'))+'">'+esc(type)+'</span><strong>'+esc(e.title)+'</strong><small>'+esc(e.form||e.source.name)+'</small></div><span class="ce-expand" aria-hidden="true">+</span></summary><div class="ce-body"><p>'+esc(e.summary||'상세 내용은 원문에서 확인하세요.')+'</p>'+(fields.length?'<dl>'+fields.map(x=>'<div><dt>'+esc(x.label)+'</dt><dd>'+esc(x.value)+'</dd></div>').join('')+'</dl>':'')+(e.form?.startsWith('8-K')?'<small>공시일은 사건 발생일·실적 발표일과 다를 수 있습니다. '+(e.items?.length?'공시 항목 '+esc(e.items.join(', '))+'. ':'')+'구체적인 조건과 내용은 원문을 확인하세요.</small>':'')+'<div class="ce-source"><a href="'+esc(e.source.url)+'" target="_blank" rel="noopener noreferrer">'+esc(e.source.name)+' 원문 ↗</a><small>확인 '+confirmed(e.observedAt)+'</small></div></div></details></li>';
}
function panel(ticker,snapshot=data,now=Date.now()){
 const s=select(snapshot,ticker,now),list=rows=>'<ol class="ce-list">'+rows.map(e=>card(e,s.today)).join('')+'</ol>';
 const state=s.fresh?'최근 공시 확인':s.checkedAt?'마지막 확보 자료':s.past.length?'회사 발표 연결':failed?'자료 읽기 실패':snapshot?'공시 수집 대기':'자료 확인 중';
 let content='<h4>다가오는 일정</h4>'+(s.upcoming.length?list(s.upcoming):'<p class="ce-empty">최신 예정 일정 확인 자료가 없습니다.</p>')+'<h4>최근 180일</h4>';
 content+=s.past.length?list(s.past.slice(0,4)):'<p class="ce-empty">'+(s.fresh?'확인한 공시 범위에 최근 표시할 항목이 없습니다.':'최근 공시 확인 자료가 없습니다. 원문으로 확인하세요.')+'</p>';
 if(s.past.length>4)content+='<details class="ce-more"><summary>이전 공시 '+(s.past.length-4)+'개 더 보기</summary>'+list(s.past.slice(4))+'</details>';
 const cik=s.issuer?.cik,edgar=Number.isInteger(cik)&&cik>0?'<a href="https://www.sec.gov/edgar/browse/?CIK='+cik+'&owner=exclude" target="_blank" rel="noopener noreferrer">SEC 전체 공시 ↗</a>':'';
 return '<section class="company-events" data-event-symbol="'+esc(s.key)+'" aria-label="'+esc(s.key)+' 회사 이벤트"><div class="ce-heading"><div><small>COMPANY EVENTS · '+esc(s.key)+'</small><h3>회사 이벤트 타임라인</h3></div><span class="ce-status'+(s.fresh?' ce-ready':'')+'">'+state+'</span></div>'+(!s.fresh&&s.checkedAt?'<p class="ce-collection">수집 지연 · 마지막 공시 확인 '+confirmed(s.checkedAt)+'</p>':'')+content+'<footer>'+edgar+'<details><summary>출처·수집 범위</summary><p>SEC 주요 사항·정기 보고서·주주총회 자료를 공시일 순으로 표시합니다. 회사 원문 실적 요약은 NVDA·MSFT에 연결되어 있습니다. 예상 실적일은 Yahoo 제공 자료로, 회사 확정 일정과 구분합니다.</p><p>SEC 확인 '+confirmed(s.checkedAt)+'. 수집 누락은 사건이 없다는 뜻이 아닙니다. 사건의 주가 영향은 별도로 판단하세요.</p></details></footer></section>';
}
async function load(fetcher=root.fetch?.bind(root),force=false){
 if(loading&&!force)return loading;
 loading=(async()=>{try{const r=await fetcher('events/latest.json',{cache:'no-store'});if(!r.ok)throw Error('events');const x=await r.json();if(x?.schemaVersion!==1||!x.issuers||!x.symbols)throw Error('schema');data=x;failed=false}catch(_){data=null;failed=true}return data})();
 return loading;
}
function mount(host,ticker){
 if(!host)return;const key=normalize(ticker);host.dataset.eventSymbol=key;host.innerHTML=panel(key);
 load().then(()=>{if(host.isConnected&&host.dataset.eventSymbol===key)host.innerHTML=panel(key)});
}
const api={load,panel,select,mount,safeSource};if(typeof module!=='undefined')module.exports=api;else root.CompanyEvents=api;
})(typeof window!=='undefined'?window:globalThis);
