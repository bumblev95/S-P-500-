(function(root){
  'use strict';
  const finite=Number.isFinite,DAY=86400000;
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function nyDate(now){
    const parts=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(now));
    const q=Object.fromEntries(parts.map(p=>[p.type,p.value]));return q.year+'-'+q.month+'-'+q.day;
  }
  function weekBounds(now){
    const d=new Date(nyDate(now)+'T00:00:00Z');d.setUTCDate(d.getUTCDate()-(d.getUTCDay()+6)%7);
    const start=d.toISOString().slice(0,10);d.setUTCDate(d.getUTCDate()+4);return {start,end:d.toISOString().slice(0,10)};
  }
  const validDate=d=>typeof d==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(d)&&finite(Date.parse(d))&&new Date(d).toISOString().slice(0,10)===d;
  const freshDate=(d,now)=>validDate(d)&&d<=nyDate(now)&&(Date.parse(nyDate(now))-Date.parse(d))/DAY<=5;
  const freshTime=(d,now,days)=>finite(Date.parse(d))&&now>=Date.parse(d)&&now-Date.parse(d)<=days*DAY;
  const pct=x=>finite(x)?(x>0?'+':x<0?'−':'')+Math.abs(x).toFixed(2)+'%':'자료 없음';
  const short=d=>validDate(d)?d.slice(5).replace('-','.'):'확인 중';
  function safeUrl(value){try{const u=new URL(value);return u.protocol==='https:'&&['www.federalreserve.gov','www.bbc.com','www.bbc.co.uk','bbc.com','bbc.co.uk','www.cnbc.com','cnbc.com'].includes(u.hostname)&&!u.username&&!u.password;}catch(_){return false;}}
  const icon=name=>'<i data-lucide="'+(['cpu','radio','shopping-bag','landmark','factory','heart-pulse','shopping-basket','house','zap','flask-conical','fuel','clock-3','trending-up','trending-down','minus','arrow-down-left','arrow-up-right'].includes(name)?name:'minus')+'" aria-hidden="true"></i>';
  function breaking(item,now){return item.importance==='important'&&!item.fromCache&&item.sourceStatus==='ready'&&freshTime(item.firstPublishedAt||item.publishedAt,now,2/24);}
  function eligibleNews(items,now){return (items||[]).filter(a=>a.translationStatus==='ready'&&a.headlineKo&&safeUrl(a.url)&&freshTime(a.publishedAt,now,14)).slice(0,5);}
  function rankRows(rows,now){
    const seen=new Set();
    return (Array.isArray(rows)?rows:[]).filter(q=>{
      if(!q||!/^[A-Z0-9]+(?:[.-][A-Z0-9]+)?$/.test(q.symbol)||seen.has(q.symbol)||!validDate(q.asOf)||!freshTime(q.asOf,now,5))return false;
      seen.add(q.symbol);return true;
    }).slice(0,3);
  }
  function rankingSignal(q,type){
    if(type==='sell')return {label:({reduce:'축소 검토',protect:'이탈 주의',hold:'상대 하위'})[q.holdingCode]||'조건 확인',tone:q.holdingCode==='reduce'?'sell':'caution'};
    const labels={buy:'조건 충족',breakout:'돌파 확인',pullback:'눌림 확인',riskwait:'위험 확인',overextended:'추격 주의',confirm:'지지 확인',watch:'흐름 확인',avoid:'진입 보류',unavailable:'자료 확인'};
    return {label:Object.hasOwn(labels,q.code)?labels[q.code]:'조건 확인',tone:q.code==='buy'?'buy':'caution'};
  }
  function rankingHtml(rows,type,now){
    const list=rankRows(rows,now);
    return list.length?'<ol class="hp-rank-list" aria-label="'+(type==='buy'?'매수':'매도')+' 우선 검토 순위">'+list.map((q,i)=>{
      const signal=rankingSignal(q,type);
      return '<li><a class="hp-pick" href="stocks.html?symbol='+encodeURIComponent(q.symbol)+'" title="'+esc(q.reason||signal.label)+'" aria-label="'+esc((i+1)+'위 '+(q.name||q.symbol)+' '+q.symbol+' · '+signal.label)+'"><span class="hp-pick-main"><span class="hp-rank" aria-hidden="true">'+(i+1)+'</span><strong class="hp-name">'+esc(q.symbol)+'</strong></span><span class="hp-pick-signal hp-signal-'+signal.tone+'">'+esc(signal.label)+'</span></a></li>';
    }).join('')+'</ol>':'<p class="hp-muted">최신 순위 자료 확인 중</p>';
  }
  const buyHtml=(rankings,now)=>rankingHtml(rankings?.buy,'buy',now);
  function rankingNote(r,now){
    return (validDate(r?.asOf)?short(r.asOf)+' 종가 · ':'')+'매수·매도 우선 검토 순위 · 실제 조건은 카드에서 확인'+
      (!freshTime(r?.marketGeneratedAt,now,r?.marketMaxAgeDays||3)?' · 시장 자료 갱신 지연':'');
  }
  function quoteValues(q,recap,now){
    const current=freshDate(q.asOf,now)&&q.asOf===recap.asOf;
    const sameWeek=recap.weekStart===weekBounds(now).start;
    return {day:current&&finite(q.day)?q.day:null,week:current&&sameWeek&&finite(q.week)?q.week:null};
  }
  function chartRows(recap,now){return (recap.sectors||[]).map(q=>({...q,...quoteValues(q,recap,now)})).sort((a,b)=>finite(a.day)&&finite(b.day)?b.day-a.day:finite(a.day)?-1:finite(b.day)?1:a.name.localeCompare(b.name));}
  function scale(rows){const maximum=Math.max(0,...rows.flatMap(q=>[q.day,q.week]).filter(finite).map(Math.abs));return Math.ceil(maximum*1.12*10)/10||1;}
  function chartHtml(recap,now,selected=''){
    const rows=chartRows(recap,now),limit=scale(rows),week=weekBounds(now);
    const lane=value=>'<span class="hp-bar-lane" aria-hidden="true">'+(finite(value)?'<span class="hp-sector-bar '+(value>=0?'hp-rise':'hp-fall')+'" style="width:'+(Math.abs(value)/limit*50)+'%"></span>':'')+'</span>';
    return '<div class="hp-sector-chart" role="group" aria-label="11개 섹터 ETF 등락률. 초록 오른쪽은 상승, 빨강 왼쪽은 하락. 하루와 주간 동일 눈금."><div class="hp-chart-head"><span>섹터 ETF</span><span>하루<small>'+short(recap.asOf)+' 마감</small></span><span>이번 주<small>'+short(week.start)+'–'+short(week.end)+'</small></span></div>'+rows.map(q=>'<button type="button" class="hp-sector-row'+(q.status!=='ready'?' hp-unavailable':'')+'" data-sector="'+esc(q.symbol)+'" aria-pressed="'+String(q.symbol===selected)+'" aria-label="'+esc(q.name+' · 하루 '+pct(q.day)+' · 이번 주 '+pct(q.week)+(q.fromCache?' · 이전 수집 자료':''))+'"><span class="hp-sector-label">'+icon(q.fromCache?'clock-3':q.icon)+'<span>'+esc(q.name==='커뮤니케이션'?'통신':q.name)+'</span></span>'+lane(q.day)+lane(q.week)+'</button>').join('')+'<div class="hp-chart-axis" aria-hidden="true"><span>등락률 (%)</span><span class="hp-direction"><span>←</span><span>0</span><span>→</span></span><span class="hp-direction"><span>←</span><span>0</span><span>→</span></span></div><div class="hp-chart-legend"><span class="hp-legend-fall">'+icon('arrow-down-left')+'하락</span><span class="hp-legend-rise">'+icon('arrow-up-right')+'상승</span><span>길수록 큰 움직임</span></div><div class="hp-sector-detail" data-sector-detail aria-live="polite">하루 · 주간 같은 눈금 / 섹터별 상세</div></div>';
  }
  function newsStateHtml(state,now){
    const feeds=Array.isArray(state.feeds)?state.feeds:[];
    const failed=feeds.filter(f=>f.status!=='ready');
    const families=[...new Set(feeds.map(f=>String(f.name||'').split(/\s+/)[0]).filter(Boolean))];
    const successes=feeds.map(f=>Date.parse(f.lastSuccessAt)).filter(finite);
    const latestSuccess=successes.length?Math.max(...successes):null;
    const newsTimes=eligibleNews(state.news,now).map(q=>Date.parse(q.publishedAt)).filter(finite);
    const latestNews=newsTimes.length?Math.max(...newsTimes):null;
    const checked=latestSuccess?new Intl.DateTimeFormat('ko-KR',{timeZone:'America/New_York',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(latestSuccess))+' ET':'확인 중';
    const quiet=latestSuccess&&(!latestNews||latestSuccess-latestNews>=3600000);
    const sourceText=(families.length?families.join(' · '):'시장')+' 뉴스';
    return '<div class="hp-news-state">'+(failed.length?'<span class="hp-cache">'+esc(failed.map(f=>f.name).join(' · '))+' 갱신 지연</span>':'<span class="hp-ready-dot" aria-hidden="true"></span><span>'+esc(sourceText)+'</span>')+'<span>매시간 자동 확인</span><span>최근 정상 수집 '+esc(checked)+'</span>'+(quiet?'<span>새 주요 뉴스 없음</span>':'')+'</div>';
  }
  function newsHtml(state,now){
    const items=eligibleNews(state.news,now);
    const stories=items.map(q=>{
      const urgent=breaking(q,now),mark=q.importance==='important'?'<span class="hp-news-mark'+(urgent?' breaking':'')+'"'+(urgent?' data-breaking-until="'+(Date.parse(q.firstPublishedAt||q.publishedAt)+2*3600000)+'"':'')+' aria-label="'+esc(q.importanceReason||'시장 영향이 큰 사건')+'">'+(urgent?'속보':'중요')+'</span>':'';
      const dateText=new Intl.DateTimeFormat('ko-KR',{timeZone:'America/New_York',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(q.publishedAt));
      return '<article class="hp-story"><div class="hp-story-meta">'+mark+'<span>'+esc(q.category)+' · '+esc(q.source)+'</span><time datetime="'+esc(q.publishedAt)+'">'+esc(dateText)+' ET</time>'+(q.fromCache||q.sourceStatus!=='ready'?'<span class="hp-cache">이전 수집</span>':'')+'</div><h3><a href="'+esc(q.url)+'" target="_blank" rel="noopener noreferrer">'+esc(q.headlineKo)+'</a></h3><p>'+esc(q.summaryKo)+'</p></article>';
    }).join('');
    return (stories||'<p class="hp-empty">확인된 한국어 시장 뉴스가 아직 없습니다.</p>')+newsStateHtml(state,now);
  }
  const api={nyDate,weekBounds,freshDate,breaking,eligibleNews,rankingHtml,buyHtml,rankingSignal,rankingNote,quoteValues,chartRows,scale,chartHtml,newsHtml,newsStateHtml,rankRows};
  if(typeof module!=='undefined')module.exports=api;else root.MarketHome=api;
  if(typeof document==='undefined')return;
  const host=document.getElementById('market-home');if(!host)return;
  const params=new URLSearchParams(root.location.search);
  if(params.has('symbol')){root.location.replace('stocks.html'+root.location.search+root.location.hash);return;}
  const $=selector=>host.querySelector(selector);
  let data=null,selected='',periodKey='',loading=false,lastAttemptAt=0;
  const icons=()=>root.lucide?.createIcons({attrs:{width:16,height:16}});
  function renderRecap(now){
    const recap=data.recap||{},week=weekBounds(now),sameWeek=recap.weekStart===week.start;
    const complete=sameWeek&&recap.weekComplete;
    const indices=(recap.indices||[]).map(q=>{const v=quoteValues(q,recap,now);return '<div class="hp-index"><span class="hp-index-name">'+esc(q.name)+'</span><strong class="hp-index-value"'+(v.day<0?' style="color:var(--hp-red)"':'')+'>'+icon(finite(v.day)?v.day>=0?'trending-up':'trending-down':'minus')+(finite(v.day)?pct(v.day):'—')+'</strong><span class="hp-index-week">주간 '+(finite(v.week)?pct(v.week):'—')+'</span></div>';}).join('');
    $('[data-home-recap]').innerHTML='<div class="hp-period"><div><strong>최근 거래일 · '+short(recap.asOf)+'</strong>전 거래일 마감 대비</div><div><strong>이번 주 · 월–금</strong>'+short(week.start)+'–'+short(week.end)+' · '+(complete?'주간 완료':'진행 중')+'</div></div><div class="hp-recap-wrap"><div class="hp-benchmarks">'+indices+'</div>'+chartHtml(recap,now,selected)+'</div><div class="hp-recap-note">ETF 가격 등락 · 배당 제외 · 주간은 전주 마지막 마감 대비</div>';
    const sectors=chartRows(recap,now);
    const bad=sectors.some(q=>q.fromCache||!finite(q.day));
    $('[data-recap-state]').textContent=bad?'일부 자료 갱신 대기':'마감 기준';
    $('[data-home-recap]').querySelectorAll('[data-sector]').forEach(button=>button.addEventListener('click',()=>{
      selected=button.dataset.sector;
      $('[data-home-recap]').querySelectorAll('[data-sector]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
      const q=sectors.find(q=>q.symbol===selected);
      $('[data-sector-detail]').textContent=q.name+' · 하루 '+pct(q.day)+' / 이번 주 '+pct(q.week)+(q.fromCache?' · 이전 자료':'' );
    }));
    periodKey=week.start;icons();
  }
  function renderRankings(now){
    const r=data.rankings||{};
    $('[data-home-buy]').innerHTML=buyHtml(r,now);
    $('[data-home-sell]').innerHTML=rankingHtml(r.sell,'sell',now);
    // Cached copies of the root-domain wrapper may predate this caption.
    let note=$('[data-home-ranking-note]');
    if(!note){note=document.createElement('p');note.className='hp-rank-note';note.dataset.homeRankingNote='';$('.hp-picks').append(note);}
    note.textContent=rankingNote(r,now);
  }
  function render(now){
    renderRankings(now);
    $('[data-home-news]').innerHTML=newsHtml(data,now);
    $('[data-home-brief]').textContent=data.recap?.asOf&&freshDate(data.recap.asOf,now)?data.brief:'최근 마감 자료 갱신 대기';
    const localDate=new Intl.DateTimeFormat('ko-KR',{timeZone:'America/New_York',month:'long',day:'numeric',weekday:'long'}).format(new Date(now));
    $('[data-home-date]').innerHTML='<strong>'+esc(localDate)+' · 미국장</strong><span class="hp-status">최근 마감 · '+short(data.recap?.asOf)+'</span>';
    $('[data-home-status]').textContent='갱신 '+new Intl.DateTimeFormat('ko-KR',{timeZone:'America/New_York',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(data.generatedAt))+' ET · 최신 종가로 매일 재선정';
    renderRecap(now);icons();
  }
  async function load(){
    if(loading)return;
    loading=true;lastAttemptAt=Date.now();
    try{
      const response=await fetch('market/home.json?refresh='+Math.floor(Date.now()/60000),{cache:'no-store'});
      if(!response.ok)throw Error('Snapshot unavailable');
      const value=await response.json();if(value.schemaVersion!==1)throw Error('Unsupported snapshot');
      data=value;render(Date.now());
    }catch(_){
      $('[data-home-status]').innerHTML='시장 자료를 불러오지 못했습니다. <button type="button" data-home-retry>다시 불러오기</button>';
      if(data){renderRankings(Date.now());$('[data-home-status]').firstChild.textContent='갱신 지연 · 최근 저장 자료 표시 중. ';}
      else{
        $('[data-home-buy]').innerHTML='<p class="hp-muted">순위 자료 확인 중</p>';$('[data-home-sell]').innerHTML='<p class="hp-muted">순위 자료 확인 중</p>';
        $('[data-home-news]').innerHTML='<p class="hp-empty">뉴스 자료 확인 중</p>';$('[data-home-recap]').innerHTML='<p class="hp-empty">섹터 자료 확인 중</p>';
      }
      $('[data-home-retry]').addEventListener('click',load);
    }finally{loading=false;}
  }
  load();icons();
  setInterval(()=>{
    const now=Date.now();
    host.querySelectorAll('[data-breaking-until]').forEach(mark=>{if(now>=Number(mark.dataset.breakingUntil)){mark.textContent='중요';mark.classList.remove('breaking');mark.removeAttribute('data-breaking-until');}});
    if(!document.hidden&&now-lastAttemptAt>=5*60000)load();
    else if(data){if(periodKey!==weekBounds(now).start)render(now);else renderRankings(now);}
  },60000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&Date.now()-lastAttemptAt>=60000)load();});
})(typeof window!=='undefined'?window:globalThis);
