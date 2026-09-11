(function(){
'use strict';
const E=PerpEngine,API='https://api.hyperliquid.xyz/info',N=Number.isFinite,esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=x=>N(x)?'$'+x.toLocaleString('en-US',{maximumFractionDigits:x<1?7:x<10?4:2}):'—',pct=x=>N(x)?(x*100).toFixed(3)+'%':'—',num=x=>N(x)?x.toFixed(2):'—',compact=x=>N(x)?new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:2}).format(x):'—';
const label={'5m':'5분봉','15m':'15분봉','1h':'1시간봉','1d':'일봉'},direction={long:'상승 우세',short:'하락 우세',neutral:'방향 혼조'};
let symbol='BTC',tf='5m',snapshot=null,busy=false,sequence=0,blockedUntil=0,denied=false,failures=0,showLevels=false,controller=null;
const el=id=>document.getElementById(id),kv=(k,v)=>'<div class="kv"><span>'+esc(k)+'</span><b>'+v+'</b></div>',panel=(title,body)=>'<section class="panel"><h3>'+title+'</h3>'+body+'</section>',time=t=>N(t)?new Date(t).toLocaleString('ko-KR'):'—';
function chart(a){
 const rows=a.rows?.slice(-90)||[];if(!rows.length)return '<div class="empty">완료된 봉 자료가 부족합니다.</div>';
 const W=window.innerWidth<650?480:1000,H=410,L=64,R=18,T=25,B=40,chosen=a.side==='long'?a.long:a.side==='short'?a.short:null,marks=showLevels&&chosen?[{v:chosen.stop,c:'#ff93a3',n:'손절'},{v:chosen.target,c:'#f7d58b',n:'목표'}].filter(m=>N(m.v)&&m.v>0):[];
 const close=rows.at(-1).close,atr=a.ind.atr,drift=Math.max(-.25*atr,Math.min(.25*atr,(a.ind.ema20-a.ind.ema50)/20)),future=Array.from({length:7},(_,t)=>({t,v:close+drift*3*(1-Math.exp(-t/3))}));
 let lo=Math.min(...rows.map(r=>r.low),...marks.map(m=>m.v),...future.map(q=>q.v)),hi=Math.max(...rows.map(r=>r.high),...marks.map(m=>m.v),...future.map(q=>q.v)),pad=Math.max((hi-lo)*.1,close*.0001);lo-=pad;hi+=pad;
 const x=i=>L+(i+.5)/(rows.length+9)*(W-L-R),y=v=>T+(hi-v)/(hi-lo)*(H-T-B),width=Math.max(1,(W-L-R)/(rows.length+9)*.62);
 let svg='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="'+esc(symbol)+' '+label[tf]+' 캔들 차트">';
 for(let i=0;i<3;i++){const v=lo+(hi-lo)*i/2;svg+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+y(v)+'" y2="'+y(v)+'" stroke="#26374c"/><text x="'+(L-6)+'" y="'+(y(v)+5)+'" text-anchor="end" fill="#9aacc1" font-size="13">'+compact(v)+'</text>';}
 rows.forEach((r,i)=>{const color=r.close>=r.open?'#7bf1cb':'#ff93a3';svg+='<g><title>'+esc(time(r.t))+' · 시 '+money(r.open)+' / 고 '+money(r.high)+' / 저 '+money(r.low)+' / 종 '+money(r.close)+'</title><line x1="'+x(i)+'" x2="'+x(i)+'" y1="'+y(r.high)+'" y2="'+y(r.low)+'" stroke="'+color+'"/><rect x="'+(x(i)-width/2)+'" y="'+Math.min(y(r.open),y(r.close))+'" width="'+width+'" height="'+Math.max(1,Math.abs(y(r.open)-y(r.close)))+'" fill="'+color+'"/></g>';});
 svg+='<polyline points="'+future.map(q=>x(rows.length-1+q.t)+','+y(q.v)).join(' ')+'" fill="none" stroke="#69d9f8" stroke-width="2" stroke-dasharray="5 5"/>';
 marks.forEach(m=>{svg+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+y(m.v)+'" y2="'+y(m.v)+'" stroke="'+m.c+'" stroke-dasharray="5 5"/><text x="'+(L+5)+'" y="'+(y(m.v)-5)+'" fill="'+m.c+'" font-size="13">'+m.n+' '+money(m.v)+'</text>';});
 const shortTime=t=>new Date(t).toLocaleString('ko-KR',tf==='1d'?{month:'numeric',day:'numeric'}:{hour:'2-digit',minute:'2-digit'});
 svg+='<text x="'+L+'" y="'+(H-12)+'" fill="#9aacc1" font-size="13">'+shortTime(rows[0].t)+'</text><text x="'+x(rows.length-1)+'" y="'+(H-12)+'" text-anchor="end" fill="#9aacc1" font-size="13">'+shortTime(rows.at(-1).t)+'</text></svg>';return svg;
}
function render(){
 if(!snapshot)return;const a=E.analyze(snapshot,tf),q=snapshot.quote||{},tone=a.action.startsWith('롱')?'green':a.action.startsWith('숏')?'red':'yellow';
 const fresh=N(snapshot.receivedAt)&&Date.now()-snapshot.receivedAt<=90000&&!snapshot.error;
 el('updated').textContent=(busy?'갱신 중 · ':fresh?'자동 갱신 · ':'갱신 확인 필요 · ')+time(snapshot.receivedAt)+' · 열려 있는 동안 60초마다 확인';
 const strip='<section class="marketStrip"><b>현재 '+label[tf]+' 분석</b><span>5분·15분은 봉 하나의 길이입니다.</span><span>완료 봉만 판단 · 진행 중인 봉 제외</span></section>';
 if(!a.ind){el('app').innerHTML=strip+panel('자료 확인 · 관망','<p>가격 패턴을 계산할 연속된 완료 봉이 부족합니다.</p><p>'+esc(snapshot.error||a.blocks.join(' · '))+'</p><p>상단 새로고침으로 다시 확인할 수 있습니다. 과거 자료를 현재 신호로 대신 표시하지 않습니다.</p>');return;}
 const selected=a.side==='long'?a.long:a.side==='short'?a.short:null;
 let graph='<div class="chartHeader"><div><span class="eyebrow">'+esc(symbol)+' · '+label[tf]+'</span><h2>'+esc(a.pattern.name)+'</h2></div><div class="price">'+money(q.mark)+'<br><small>Hyperliquid 마크 가격</small></div></div><div class="chartModes"><button id="levelToggle" aria-pressed="'+showLevels+'">손절·목표선 '+(showLevels?'숨기기':'보기')+'</button></div><div class="chart">'+chart(a)+'</div><p class="chartNote">봉에 마우스를 올리면 가격을 확인할 수 있습니다. 짧은 점선은 다음 6봉의 추세 지속 가정이며 학습형 예측이 아닙니다.</p>';
 graph+='<div class="outlook"><div><span>선택 봉 방향</span><strong>'+direction[a.bias]+'</strong></div><div><span>'+label[a.higher]+' 흐름 확인</span><strong>'+direction[a.hi.bias]+'</strong></div><div><span>마지막 봉의 거래량</span><strong>'+num(a.ind.relativeVolume)+'배</strong><small>직전 20봉 평균 대비</small></div></div>';
 const blocks=[...a.blocks];if(snapshot.error)blocks.unshift(snapshot.error);
 let decision='<span class="eyebrow">지금의 조건</span><div class="decisionTitle '+tone+'">'+a.action+'</div><p>'+esc(direction[a.bias])+(a.action==='관망'?' · 방향과 진입 조건은 별도입니다.':' · 현재 구간을 벗어나면 다시 확인하세요.')+'</p><div class="metrics"><div><span>롱 조건 점수</span><strong class="green">'+a.longScore+'/100</strong></div><div><span>숏 조건 점수</span><strong class="red">'+a.shortScore+'/100</strong></div></div><p class="bodyNote">점수는 승률이 아닙니다.</p>';
 if(selected)decision+=kv((a.side==='long'?'롱':'숏')+' 진입 관심 구간',money(selected.lowEntry)+'–'+money(selected.highEntry))+kv('손절 기준',money(selected.stop))+kv('목표 가격',money(selected.target))+kv('비용 반영 손익비',num(selected.rr))+ '<p class="bodyNote">목표 근거: '+esc(selected.targetKind)+'. 관망일 때는 관찰용 가격입니다.</p>';
 decision+='<ul class="reasons">'+(blocks.length?blocks.slice(0,5):['완료 봉 패턴·상위 흐름·거래량·현재가·비용 조건 충족']).map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul><p class="bodyNote">분석 봉 마감: '+time(a.signalAt)+'<br>다음 봉 마감 또는 가격 이탈 시 재평가</p>';
 let html=strip+'<div class="workspace">'+panel('',graph)+'<aside>'+panel('',decision)+'</aside></div>';
 const rows=Object.entries(label).map(([i,l])=>{const ind=E.indicators(snapshot.frames[i]||[],i);return kv(l,ind?direction[ind.bias]:'자료 부족');}).join('');
 html+='<div class="detailsGrid">'+panel('왜 이런 방향인가?',kv('20 / 50봉 지수이동평균',money(a.ind.ema20)+' / '+money(a.ind.ema50))+kv('RSI · 과열 확인',num(a.ind.rsi))+kv('MACD 히스토그램',num(a.ind.macd))+kv('봉 기준 거래량가중평균',money(a.ind.vwap))+kv('ATR · 평균 봉 변동폭',money(a.ind.atr))+kv('20봉 방향성 효율',num(a.ind.efficiency))+'<p class="bodyNote">방향성 효율이 0에 가까우면 등락만 반복하는 횡보에 가깝습니다.</p>')+panel('다른 봉에서는?',rows+'<p class="bodyNote">5분봉은 15분봉, 15분봉은 1시간봉과 같은 방향이어야 진입 조건을 통과합니다. 일봉은 독립적으로 평가합니다.</p>')+panel('거래 비용과 유동성',kv('시간당 펀딩비',pct(q.funding))+kv('펀딩 방향',N(q.funding)?q.funding>0?'롱 지급 → 숏 수취':q.funding<0?'숏 지급 → 롱 수취':'현재 0':'—')+kv('24시간 선물 거래대금','$'+compact(q.volume24h))+kv('미결제약정','$'+compact(q.oiUSD))+kv('최우선 호가 간격',pct(snapshot.book?.spread))+kv('마크 / 오라클 괴리',pct(q.premium))+'<p class="bodyNote">손익비에는 편도 수수료 0.045%와 편도 슬리피지 가정 0.02%, 선택 주기 6봉 동안의 현재 지급 펀딩비를 반영합니다. 실제 비용은 달라질 수 있습니다.</p>')+'</div>';
 html+=panel('계산 근거와 사용 범위','<details><summary>패턴·진입 조건 자세히 보기</summary><p>직전 20봉 고저 돌파는 거래량 1.3배 이상, 20봉 EMA 눌림·반등 패턴은 0.8배 이상을 요구합니다. 장악형은 두 봉의 몸통과 추세를 함께 확인합니다. 미완성 봉은 포함하지 않습니다. 가격 방향은 EMA20/50, Wilder RSI14, MACD12/26/9, 봉 기반 VWAP를 사용합니다. VWAP는 분봉에서 UTC 당일, 일봉에서 최근 20봉 기준이며 체결 단위 VWAP와 다릅니다.</p><p>손절은 이전 지지·저항 바깥 0.25 ATR, 목표는 양옆 두 봉으로 확인된 고저 피벗입니다. 돌파 후 관측 저항이 없으면 직전 박스 폭 투영을 별도 표기합니다. 손익비를 맞추려고 목표를 올리지 않습니다. 현재 마크 가격이 확인 봉 종가 ±0.15 ATR를 벗어나면 추격 진입을 보류합니다.</p><p>가격·호가는 90초, 완료 봉은 해당 봉 길이 + 15초를 넘으면 신규 판단을 보류합니다. 신호는 보유 포지션의 관리 지시가 아니며 초단타 체결 지연·호가 깊이·청산맵을 검증하지 않습니다. 언락·뉴스·시장 충격은 이 단기 점수에 포함되지 않습니다. 학습형 AI나 수익성 백테스트를 통과한 전략은 아닙니다.</p><p><a href="https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint" target="_blank" rel="noopener noreferrer">가격·봉 데이터 출처</a> · <a href="https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees" target="_blank" rel="noopener noreferrer">거래 수수료 기준</a></p></details>');
 el('app').innerHTML=html;el('levelToggle').addEventListener('click',()=>{showLevels=!showLevels;render()});
}
async function request(body,signal){
 if(denied||Date.now()<blockedUntil)throw Error('거래소 요청 제한 · 잠시 후 확인');
 const r=await fetch(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});
 if(r.status===401||r.status===403){denied=true;throw Error('거래소 접근 제한 · 자동 요청 중지');}
 if(r.status===429){const retry=Number(r.headers.get('Retry-After'));blockedUntil=Date.now()+Math.max(60000,N(retry)?retry*1000:300000);throw Error('거래소 요청 한도 · 대기 후 다시 확인');}
 if(!r.ok)throw Error('거래소 데이터 응답 오류');return r.json();
}
async function load(){
 if(busy||denied||Date.now()<blockedUntil)return;
 const ticket=++sequence,coin=symbol,started=Date.now();busy=true;el('refresh').disabled=true;el('updated').textContent='최신 봉·가격·호가 확인 중';controller=new AbortController();const active=controller;const timeout=setTimeout(()=>active.abort(),18000);
 try{
  const jobs=[{type:'metaAndAssetCtxs'},{type:'l2Book',coin},...Object.keys(E.MS).map(i=>({type:'candleSnapshot',req:{coin,interval:i,startTime:started-E.MS[i]*242,endTime:started}}))];
  const responses=await Promise.allSettled(jobs.map(body=>request(body,active.signal)));if(ticket!==sequence||coin!==symbol)return;
  const next=snapshot?.symbol===coin?{...snapshot,frames:{...snapshot.frames}}:{symbol:coin,frames:{}};let failed=false;
  responses.forEach((r,i)=>{if(r.status==='rejected'){failed=true;return;}try{if(i===0){const [meta,ctx]=r.value,k=meta.universe.findIndex(a=>a.name===coin);if(k<0)throw Error();const c=ctx[k],mark=Number(c.markPx),oracle=Number(c.oraclePx);const numeric=v=>v===null||v===''||v===undefined?null:Number(v);next.quote={mark,oracle,funding:numeric(c.funding),premium:oracle>0?mark/oracle-1:null,oiUSD:numeric(c.openInterest)===null?null:Number(c.openInterest)*mark,volume24h:numeric(c.dayNtlVlm),delisted:!!meta.universe[k].isDelisted};next.quoteAt=started;}
   else if(i===1){const b=r.value,bid=Number(b.levels[0][0].px),ask=Number(b.levels[1][0].px);next.book={bid,ask,spread:(ask-bid)/((ask+bid)/2)};next.bookAt=b.time;}
   else{const interval=Object.keys(E.MS)[i-2],rows=E.candles(r.value,interval,Date.now(),coin);if(rows.length<60)throw Error();next.frames[interval]=rows;}}catch(_){failed=true;}});
  next.error=failed?(denied?'거래소 접근 제한 · 자동 요청 중지':Date.now()<blockedUntil?'요청 한도 대기 · 신규 신호 보류':'일부 봉·가격을 갱신하지 못해 신규 신호를 보류합니다.'):null;
  if(!failed){next.receivedAt=Date.now();failures=0;}else{failures++;blockedUntil=Math.max(blockedUntil,Date.now()+Math.min(300000,30000*2**Math.min(failures,4)));}
  snapshot=next;
 }catch(_){if(ticket===sequence){snapshot=snapshot||{symbol:coin,frames:{}};snapshot.error='연결을 확인할 수 없어 신규 신호를 보류합니다.';}}
 finally{clearTimeout(timeout);if(ticket===sequence){busy=false;el('refresh').disabled=denied;render();}}
}
el('coin').addEventListener('change',()=>{symbol=el('coin').value;sequence++;controller?.abort();busy=false;snapshot=null;showLevels=false;el('app').innerHTML=panel('자료 확인 중','<p>'+esc(symbol)+' 최신 봉을 불러옵니다.</p>');load();if(denied||Date.now()<blockedUntil)el('app').innerHTML=panel('관망','<p>거래소 접근·요청 제한으로 대기 중입니다. 제한이 풀린 뒤 새로고침해 주세요.</p>');});
document.querySelectorAll('[data-tf]').forEach(b=>b.addEventListener('click',()=>{tf=b.dataset.tf;document.querySelectorAll('[data-tf]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));showLevels=false;render()}));
el('refresh').addEventListener('click',load);document.addEventListener('visibilitychange',()=>{if(!document.hidden)load()});
setInterval(()=>{if(!document.hidden)load()},60000);setInterval(()=>{if(!document.hidden)render()},15000);load();
})();
