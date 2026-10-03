(function(){
'use strict';
const finite=Number.isFinite,esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const gates={immutableEvidence:'불변 기록 검증',completeData:'실행 자료 완전성',matchedForwardSample:'같은 기간 비교',minimumTrades:'최소 표본',purgedWalkForward:'시간순 독립 검증',costIncludedImprovement:'비용 포함 개선',drawdownNotWorse:'낙폭 악화 방지',riskNotWorse:'위험 악화 방지'};
const statuses={insufficient:['표본 부족','waiting'],rejected:['검증 기준 미충족','failed'],promotion_candidate:['사람 검토 후보','passed'],blocked:['검증 차단','failed']};
const badge=(text,tone)=>'<span class="shadow-badge '+tone+'"><i aria-hidden="true"></i>'+esc(text)+'</span>';
const pct=x=>finite(x)?(100*x).toFixed(2)+'%':'—',pp=x=>finite(x)?(100*x).toFixed(2)+' pp':'—';
const stamp=x=>Number.isSafeInteger(x)&&x>=0&&x<8640000000000000?new Date(x).toISOString().slice(0,16).replace('T',' ')+' UTC':'—';
function safeSummary(d){return d?.schemaVersion===1&&d.purpose==='display-only'&&d.mode==='shadow-only'&&Number.isSafeInteger(d.generatedAt)&&d.generatedAt>=0&&d.generatedAt<8640000000000000&&Array.isArray(d.versions)&&d.automaticPromotion===false&&d.defaultStrategyChanged===false&&d.pinnedModelChanged===false&&d.liveTrading===false&&d.humanReviewRequired===true;}
function safeVersion(v){
 const a=v?.assessment;
 return v?.integrityPassed===true&&v.status===a?.status&&(v.status==='promotion_candidate')===v.promotionCandidate&&a?.mode==='shadow-only'&&a.candidateVersion===v.version&&finite(v.thresholdR)&&finite(v.incumbentThresholdR)&&v.thresholdR>v.incumbentThresholdR&&Object.keys(gates).every(k=>typeof a.gates?.[k]==='boolean')&&a.automaticPromotion===false&&a.defaultStrategyChanged===false&&a.pinnedModelChanged===false&&a.liveTrading===false&&a.promotionCandidate===v.promotionCandidate&&v.promotionCandidate===Object.keys(gates).every(k=>a.gates[k]);
}
function localPath(path){return /^simulation\/self-improvement\/versions\/shadow-threshold-v1-\d+-[a-f0-9]{12}\/(?:candidate\.json|(?:observations|assessments)\/\d+-[a-f0-9]{12}\.json)$/.test(path||'')?path:null;}
function progress(title,current,target,unit){
 const value=finite(current)?Math.max(0,current):0,limit=finite(target)&&target>0?target:1;
 return '<article class="shadow-progress"><span>'+title+'</span><strong>'+value.toLocaleString('ko-KR',{maximumFractionDigits:1})+' <small>/ '+limit+' '+unit+'</small></strong><progress aria-label="'+title+'" max="'+limit+'" value="'+Math.min(value,limit)+'"></progress></article>';
}
function forecast(context){
 if(!context)return '';
 return '<details class="shadow-details"><summary>별도 주가 예측 연구 · 126일 / 252일</summary><p class="muted">'+esc(context.generatedAt||'시각 미제공')+' 기준 · shadow 거래 성과와 승격 gate에 합산하지 않습니다.</p><div class="shadow-forecast">'+['126','252'].map(h=>{
  const c=context.horizons?.[h];if(!c)return '<article><b>'+h+'일</b>'+badge('자료 없음','waiting')+'</article>';
  const state=c.status==='insufficient'?['독립 표본 부족','waiting']:c.passed===true?['연구 gate 통과','passed']:['연구 gate 미통과','failed'];
  return '<article><b>'+h+'일</b>'+badge(...state)+'<dl><div><dt>연구 후보</dt><dd>'+esc(c.chosen||'—')+'</dd></div><div><dt>원본 대비 개선</dt><dd>'+(finite(c.improvementVsOriginal)?c.improvementVsOriginal.toFixed(6):'—')+'</dd></div><div><dt>실제 예측 반영</dt><dd>'+(c.liveForecastChanged===true?'변경됨':'변경 없음')+'</dd></div></dl>'+(c.reason?'<p class="muted">'+esc(c.reason)+'</p>':'')+'</article>';
 }).join('')+'</div></details>';
}
function unavailable(message){return '<section class="sim-panel shadow-panel"><div class="panel-head"><h2>자기개선 검증 현황</h2>'+badge('상태 자료 없음','waiting')+'</div><p>'+esc(message)+'</p><p class="muted">Shadow only · 자동 승격 없음 · 기존 모델과 계좌 유지</p></section>';}
function render(d,version,now=Date.now()){
 if(!safeSummary(d))return unavailable('검증 상태 자료의 형식을 확인하지 못했습니다.');
 const v=d.versions.find(x=>x.version===version)||d.versions[0],future=d.generatedAt>now,summaryStale=now-d.generatedAt>1800000;
 const verified=d.sourceIntegrity?.passed===true&&safeVersion(v)&&!future;
 const observedStale=verified&&now-v.assessment.asOf>1800000;
 const stale=summaryStale||observedStale,blocked=d.sourceIntegrity?.passed!==true||future||!!v&&!verified;
 const effective=blocked?'blocked':v?.status||'insufficient',state=statuses[effective]||statuses.blocked;
 const status=verified&&stale&&v.promotionCandidate?['평가 갱신 대기','waiting']:state;
 const a=verified?v.assessment:null,policy=a?.policy;
 let html='<section class="sim-panel shadow-panel" aria-labelledby="shadowStatusTitle"><div class="panel-head"><div><p class="eyebrow">SHADOW SELF-IMPROVEMENT</p><h2 id="shadowStatusTitle">자기개선 검증 현황</h2></div>'+badge(...status)+'</div>';
 html+='<p class="shadow-description">고정 ML 모델의 진입 기준을 새 버전으로 검증하는 <b>별도 코인 모의 연구</b>입니다. 각 후보와 비교 계좌가 $10,000으로 함께 시작합니다.</p><div class="shadow-safety">'+badge('Shadow only','neutral')+badge('Pinned 모델 고정','neutral')+badge('자동 승격 없음','neutral')+'</div>';
 if(!v){html+=blocked?'<p class="shadow-alert">후보 목록을 검증하지 못했습니다. 승격 후보로 표시할 수 없습니다.</p><p class="muted">'+esc(d.sourceIntegrity?.reason||'상태 자료 불일치 또는 미래 시각')+'</p>':'<p>등록된 shadow 후보가 없습니다.</p>';return html+forecast(d.forecastResearch)+'</section>';}
 html+='<div class="shadow-toolbar"><label for="shadowVersion">후보 버전 <select id="shadowVersion">'+d.versions.map(x=>'<option value="'+esc(x.version)+'"'+(x.version===v.version?' selected':'')+'>'+esc(x.version)+'</option>').join('')+'</select></label>'+(verified?badge(v.activity==='registration_only'?'첫 수집 대기':'전진 관측 기록 중','neutral'):'')+'</div>';
 if(stale)html+='<p class="shadow-alert">평가 갱신이 지연되었습니다. 아래는 마지막 검증 기록이며 현재 승격 가능 상태로 취급하지 않습니다.</p>';
 if(blocked)html+='<p class="shadow-alert">후보·원본·평가 기록의 검증을 완료하지 못했습니다. 승격 후보로 표시할 수 없습니다.</p><details class="shadow-details"><summary>검증 차단 사유</summary><p>'+esc(v.reason||d.sourceIntegrity?.reason||'상태 자료 불일치 또는 미래 시각')+'</p></details>';
 if(a){
  html+='<div class="shadow-progress-grid">'+progress('후보 종료 거래',a.candidate.closedTrades,policy.minClosedTrades,'건')+progress('비교 종료 거래',a.incumbent.closedTrades,policy.minClosedTrades,'건')+progress('공통 전진 관측',a.matchedForward.forwardDays,policy.minForwardDays,'일')+'</div>';
  html+='<p class="muted">독립 진입일: 후보 '+a.candidate.entryDates+' / '+policy.minEntryDates+'일 · 비교 '+a.incumbent.entryDates+' / '+policy.minEntryDates+'일. 관측 기간은 첫 공통 실행부터 계산합니다.</p>';
  if(v.activity==='registration_only')html+='<p class="muted">등록만 완료된 상태입니다. 아직 첫 실행 평가와 검증용 거래가 없습니다.</p>';
  html+='<div class="shadow-gate-grid" aria-label="승격 검증 gate">'+Object.entries(gates).map(([key,title])=>{
   const passed=a.gates[key]===true,waiting=!passed&&a.status==='insufficient'&&['matchedForwardSample','minimumTrades','purgedWalkForward','costIncludedImprovement','riskNotWorse'].includes(key);
   return '<div class="shadow-gate"><span>'+title+'</span>'+badge(stale?'마지막 평가 · '+(passed?'통과':'미통과'):passed?'통과':waiting?'검증 대기':'미통과',stale?'neutral':passed?'passed':waiting?'waiting':'failed')+'</div>';
  }).join('')+'</div>';
  if(v.promotionCandidate&&!stale)html+='<p class="shadow-review">모든 gate를 통과한 사람 검토 후보입니다. 기본 전략·고정 모델·실제 거래에 자동 반영되지 않습니다.</p>';
  html+='<details class="shadow-details"><summary>같은 기간 성과와 검증 조건</summary><div class="table-wrap"><table><caption>전체 paired 계좌 비교 · 현금·미체결·손실 포함</caption><thead><tr><th scope="col">지표</th><th scope="col">비교 '+v.incumbentThresholdR.toFixed(2)+' R</th><th scope="col">후보 '+v.thresholdR.toFixed(2)+' R</th></tr></thead><tbody>'+[
   ['종료 거래 순수익률','netReturn'],['비용 '+policy.stressCostMultiplier+'배 순수익률','stressReturn'],['보유분 포함 수익률','markedReturn'],['최대 낙폭','maxDrawdown'],['최대 명목 노출 / 자산','maxGrossExposure'],['일별 변동성','dailyVolatility']
  ].map(([title,key])=>'<tr><th scope="row">'+title+'</th><td>'+pct(a.incumbent.valid?a.incumbent[key]:null)+'</td><td>'+pct(a.candidate.valid?a.candidate[key]:null)+'</td></tr>').join('')+'</tbody></table></div><p class="muted">비용 포함 수익 개선 최소 '+pp(policy.minNetImprovement)+' · 최대 낙폭 '+pct(policy.maxDrawdown)+' 이하 및 비교 계좌보다 악화 없음.</p>';
  html+='<p class="muted">시간순 검증: '+policy.foldDays+'일 창 '+policy.purgedFolds+'개 이상 · 완료 '+a.purgedWalkForward.folds.length+'개 · 통과 '+a.purgedWalkForward.folds.filter(f=>f.passed).length+'개. 각 창 최소 '+policy.minTrainTrades+'개 학습 거래 / '+policy.minTrainDates+'개 진입일, 각 계좌 '+policy.minTestTrades+'개 검증 거래 · 경계 표본 제거와 '+policy.embargoMs/86400000+'일 간격 적용.</p>';
  if(v.initialTrainingTrades<policy.minTrainTrades)html+='<p class="shadow-alert">이 버전의 최초 학습 표본은 '+v.initialTrainingTrades+' / '+policy.minTrainTrades+'건입니다. 이후 거래가 늘어도 첫 검증 창의 부족 결과는 지우지 않습니다.</p>';
  html+='<p class="muted">수수료·슬리피지·펀딩 포함. 비용 2배는 기록된 체결에 추가 비용을 차감하는 진단입니다. 낙폭은 15분봉 마감 평가이며 장중 최대 손실을 보장하지 않습니다.</p></details>';
 }
 html+='<details class="shadow-details"><summary>기록 시각과 검증 자료</summary><dl class="shadow-meta"><div><dt>마지막 평가</dt><dd>'+stamp(a?.asOf)+'</dd></div><div><dt>표시 자료 생성</dt><dd>'+stamp(d.generatedAt)+'</dd></div><div><dt>등록 시각</dt><dd>'+stamp(v.registeredAt)+'</dd></div>'+(d.sources?'<div><dt>원본 결정 기록</dt><dd>'+d.sources.decisionRecords+'개 · 검증용 shadow 거래 수와 별도</dd></div>':'')+'</dl><p>'+[['후보 원본',v.candidatePath],['관측 원본',v.observationPath],['평가 원본',v.assessmentPath]].filter(([,p])=>localPath(p)).map(([title,p])=>'<a href="'+p+'">'+title+'</a>').join(' · ')+'</p><p><a href="simulation/self-improvement/README.md">검증 방법</a> · <a href="simulation/self-improvement/status.json">표시용 상태 자료</a></p></details>';
 return html+forecast(d.forecastResearch)+'</section>';
}
async function mount(element,fetcher=fetch,clock=Date.now){
 let data,selected,expiryTimer,lastHTML;
 const paint=()=>{
  if(element.isConnected===false)return;
  const now=clock(),html=render(data,selected,now);
  if(html!==lastHTML){element.innerHTML=html;lastHTML=html;
   const select=document.getElementById('shadowVersion');
   if(select)select.addEventListener('change',()=>{selected=select.value;paint();});
  }
  // An open page must also lose eligibility when its last record expires.
  if(typeof clearTimeout==='function')clearTimeout(expiryTimer);
  const v=data?.versions?.find(x=>x.version===selected)||data?.versions?.[0];
  const next=[data?.generatedAt,v?.assessment?.asOf].filter(Number.isSafeInteger).map(t=>t+1800001).filter(t=>t>now);
  if(typeof setTimeout==='function'&&next.length)expiryTimer=setTimeout(paint,Math.min(1800001,Math.min(...next)-now));
 };
 const refresh=async()=>{
  try{const response=await fetcher('simulation/self-improvement/status.json',{cache:'no-store'});if(!response.ok)throw Error('Unavailable');data=await response.json();paint();}
  catch{data=null;lastHTML=unavailable('상태 자료를 불러오지 못했습니다. 기존 모의운용 기록은 계속 확인할 수 있습니다.');element.innerHTML=lastHTML;if(typeof clearTimeout==='function')clearTimeout(expiryTimer);}
 };
 await refresh();
 if(typeof setInterval==='function'){
  const poll=setInterval(()=>{if(element.isConnected===false){clearInterval(poll);return;}refresh();},300000);
 }
}
window.ShadowStatus={render,mount};
const element=document.getElementById('shadowImprovementApp');if(element)mount(element);
})();
