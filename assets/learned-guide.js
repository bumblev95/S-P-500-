(function(root){
  'use strict';
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pct=x=>Number.isFinite(x)?(100*x).toFixed(1):'—';
  function inspect(data,e,h,now=Date.now()){
    const item=data?.stocks?.[e.symbol],record=item?.predictions?.[String(h)],f=record?.forecast;
    const age=(now-Date.parse(data?.generatedAt))/86400000,priceAge=(now-Date.parse(e.asOf))/86400000;
    const aligned=item?.asOf===e.asOf&&Number.isFinite(item?.price)&&Math.abs(item.price/e.price-1)<.001;
    const valid=f&&[f.anchor,f.base,f.bear,f.bull].every(v=>Number.isFinite(v)&&v>0)&&f.bear<=f.base&&f.base<=f.bull&&[f.logReturn,f.lowLogReturn,f.highLogReturn].every(Number.isFinite);
    const consistent=valid&&Math.abs(f.anchor/item.price-1)<1e-6&&[['base','logReturn'],['bear','lowLogReturn'],['bull','highLogReturn']].every(([price,r])=>Math.abs(Math.log(f[price]/f.anchor)-f[r])<1e-6);
    const reference=Date.parse(item?.asOf),training=record?.training;
    const causal=!training||[training.trainTargetThrough,training.calibrationTargetThrough].every(d=>Number.isFinite(Date.parse(d))&&Date.parse(d)<reference);
    const researchValid=data?.status==='trained'&&consistent&&Number.isFinite(reference)&&reference<=now&&causal;
    const current=aligned&&age>=0&&age<=5&&priceAge>=0&&priceAge<=5;
    const eligible=researchValid&&record?.status==='eligible'&&current;
    const reason=!record?'학습에 필요한 가격 이력 확인 중':!researchValid?'예측 파일·학습 기준일 검증 필요':!current?'이전 기준 전망 · 최신 가격과 날짜가 다릅니다':(record.reasons||[]).join(' · ')||'과거 검증 기준 통과';
    // Research display is independent of eligibility for trading/ranking.
    return {eligible,current,record,reason,asOf:item?.asOf,forecast:eligible?f:null,researchForecast:researchValid?f:null};
  }
  function chartEntry(data,e,h){
    const a=inspect(data,e,h);if(!a.researchForecast)return e;
    return {...e,price:a.researchForecast.anchor,asOf:a.asOf,history:(e.history||[]).filter(q=>q.date<=a.asOf)};
  }
  function allPeriods(data,e,now=Date.now()){
    return Object.fromEntries([21,84,252].map(h=>{const a=inspect(data,e,h,now),f=a.researchForecast;
      return [h,f&&a.asOf===e.asOf&&Math.abs(f.anchor/e.price-1)<.001?f:e.predictions?.[String(h)]?.anchor===e.price?e.predictions[String(h)]:null];}));
  }
  function horizonPanel(data,e,h){
    const rows=[21,84,252].map(k=>{const a=inspect(data,e,k),f=a.researchForecast||e.predictions?.[k];return `<div class="periodCell ${k===h?'selected':''}"><b>${k===21?'1개월':k===84?'4개월':'1년'}</b><strong>${f?pct(f.base/f.anchor-1)+'%':'—'}</strong><span>${a.eligible?'AI 검증 기준 통과':a.researchForecast?'AI 연구 · 검증 미통과':'기존 추세 · AI 자료 없음'}</span></div>`});
    const d=data?.validation?.[h]?.diagnostics,labels={above200:'200일선 위',below200:'200일선 아래',highVolatility:'높은 변동성',lowerVolatility:'낮은 변동성',overbought:'RSI 과매수',oversold:'RSI 과매도'};
    return `<section class="periodComparison" aria-label="기간별 전망과 AI 검증"><div class="periodGrid">${rows.join('')}</div><p>각 기간의 최신 AI 연구 결과를 검증 등급과 함께 표시합니다. 수익률은 원래 모델 기준가 대비입니다. 같은 기준일의 1개월·4개월 경로는 1년 경로의 일부입니다. 21·84·252 거래일 기준이며 중간 경로는 일별 AI 예측이 아닙니다.</p><details><summary>기간별 검증 · 패턴별 결과</summary><p>모델 ${esc(data?.model||'자료 없음')} · 자료 ${esc(data?.generatedAt?.slice(0,10)||'—')}. 방향 일치는 과거 결과이며 상승 확률이 아닙니다.</p>${[21,84,252].map(k=>{const m=data?.validation?.[k]||{};return `<p>${k===21?'1개월':k===84?'4개월':'1년'}: ${m.dates||0}개 시험 시점 · AI 오차 ${pct(m.mae)}%p / 가격 불변 ${pct(m.noChangeMae)}%p / 추세 ${pct(m.trendMae)}%p · 전체 기준 ${m.passed?'통과':'미통과·자료 확인'}</p>`}).join('')}${d?`<p>선택 기간에서 두 비교 방법보다 오차가 작았던 시점: ${pct(d.dateWinRate)}%. 가장 나빴던 시험 시점의 평균 오차: ${pct(d.worstDateMae)}%p.</p><div class="marketTable"><table><thead><tr><th>당시 패턴</th><th>시점 수</th><th>AI 오차</th><th>불변 / 추세 오차</th></tr></thead><tbody>${Object.entries(d.regimes||{}).map(([k,m])=>`<tr><td>${labels[k]||esc(k)}</td><td>${m.dates||0}</td><td>${pct(m.mae)}%p</td><td>${pct(m.noChangeMae)} / ${pct(m.trendMae)}%p</td></tr>`).join('')}</tbody></table></div><p>패턴별 표는 같은 외부표본을 나눈 진단입니다. 소수 시점·겹치는 그룹의 결과로 패턴의 유효성을 확정할 수 없습니다.</p>`:'<p>확장된 패턴별 진단 결과는 아직 준비되지 않았습니다.</p>'}</details></section>`;
  }
  function comparisonPanel(data,h,comparison){
    const c=comparison?.horizons?.[String(h)];
    if(!c)return '<details><summary>더 엄격한 백테스트 비교</summary><p>비교 결과를 준비 중입니다.</p></details>';
    const names={noChange:'가격 불변',trend:'기존 추세',learned:'학습형 AI',selector:'과거 성적에 따라 선택'};
    const rows={...c.laterDates,selector:c.selector};
    return `<details><summary>더 엄격한 백테스트 비교</summary><p>전체 수집 종목 비교입니다. 먼저 이전 시점의 성적으로 모델을 고르고, 그 뒤의 ${c.selector.dates}개 시점에서 시험했습니다. 선택한 종목만의 성적이 아닙니다.</p><div class="marketTable"><table class="comparisonTable"><thead><tr><th>방법</th><th>평균 오차</th><th>큰 오차</th></tr></thead><tbody>${Object.entries(rows).map(([k,v])=>`<tr><td>${names[k]}</td><td>${pct(v.mae)}%p</td><td>${pct(v.p90Error)}%p</td></tr>`).join('')}</tbody></table></div><p>작을수록 좋습니다. ‘큰 오차’는 과거 수익률 예측 오차의 90백분위이며 투자 손실이나 최대 낙폭이 아닙니다. 모든 방법은 같은 시험 시점으로 비교했습니다.</p><p>이 선택 방식도 과거 기록으로 만든 연구 결과이며 앞으로의 우위를 보장하지 않습니다. 현재 AI 채택 기준과 목표 가격을 자동 변경하지 않습니다. 비교 자료: ${esc(c.sourceGeneratedAt?.slice(0,10)||'—')}${c.sourceGeneratedAt!==data?.generatedAt?' · 이전 학습 실행의 결과':''}.</p></details>`;
  }
  function panel(data,e,h,comparison){
    const x=inspect(data,e,h),m=x.record?.validation||{},g=data?.validation?.[String(h)]||{},f=x.researchForecast;
    const money=v=>'$'+v.toLocaleString('en-US',{maximumFractionDigits:2});
    return `<div class="learnedSummary"><div class="learnedTitle"><b>${x.eligible?'AI 연구 전망 · 검증 기준 통과':f?'AI 연구 전망 · 검증 미통과':'AI 연구 자료 없음'}</b><span>${esc(data?.model||'모델 확인 필요')}</span></div><p>${esc(x.reason)}</p>${f?`<p>모델 기준 ${esc(x.asOf)} · ${money(f.anchor)} → ${h}거래일 뒤 연구 목표 ${money(f.base)}. 최신 종가와 달라도 원래 목표가를 바꾸지 않습니다.</p>`:'<p>학습 결과가 없거나 유효하지 않아 기존 추세 계산을 참고용으로 표시합니다.</p>'}<div class="validationGrid"><div>수익률 평균 오차 · MAE<strong>${pct(m.mae)}%p</strong></div><div>과거 방향 오류율<strong>${Number.isFinite(m.directionAccuracy)?pct(1-m.directionAccuracy)+'%':'—'}</strong></div><div>검증 표본<strong>${m.n||0}회 · ${m.dates||0}개 시점</strong></div><div>과거 참고 범위 포함률<strong>${pct(m.rangeCoverage)}%</strong></div></div><p>방향은 상승·중립(±2%)·하락으로 비교합니다. 과거 오류율은 이번 예측의 실패 확률이 아닙니다.${(m.dates||0)<6?' 검증 시점이 6개 미만이므로 성적이 불안정합니다.':''}</p><details><summary>이 예측을 믿을 근거는?</summary><p>학습 결과 생성 ${esc(data?.generatedAt||'—')}. 수집 종목의 가격·거래량·SPY 흐름을 학습한 모델이며 뉴스·실적은 학습하지 않습니다.</p><p>같은 표본의 수익률 평균 오차: AI ${pct(m.mae)}%p / 가격 불변 ${pct(m.noChangeMae)}%p / 기존 추세 ${pct(m.trendMae)}%p. %p는 실제와 예상 수익률의 차이로, 현물 페이지의 가격 MAPE(%)와 다른 척도입니다.</p><p>전체 검증 ${g.dates||0}개 시점 / ${g.n||0}개 종목·시점 조합. 종목들이 같이 움직이므로 모두 독립된 시험은 아닙니다. 범위는 과거 교정 오차의 10·90 분위수이며 미래 포함 확률을 보장하지 않습니다. 검증 미통과 연구값의 표시는 매수 조건을 통과시킨다는 뜻이 아닙니다.</p><p>1년 목표가가 현재와 비슷해도 그 사이의 움직임은 클 수 있습니다. AI 목표 방향과 실제 변동성은 서로 다른 값입니다. 배당·거래비용·체결을 반영한 실전 성과는 아직 검증하지 않았습니다.</p></details></div>`;
  }
  function nextSteps(plan,price,context={}){
    const money=x=>Number.isFinite(x)?'$'+x.toFixed(2):'자료 확인 후';
    const hasZone=Number.isFinite(plan.buyLow)&&Number.isFinite(plan.buyHigh),inside=hasZone&&price>=plan.buyLow&&price<=plan.buyHigh;
    const location=!hasZone?'관심 구간 자료 부족':inside?'관심 구간 안':price>plan.buyHigh?'관심 구간보다 '+pct(price/plan.buyHigh-1)+'% 위':'관심 구간보다 '+pct(1-price/plan.buyLow)+'% 아래';
    const threshold=plan.market==='watch'?2:1.5,rr=Number.isFinite(plan.rr)?plan.rr.toFixed(2):'계산 불가';
    const marketNames={stable:'관측 지표에 뚜렷한 경고 없음',watch:'주의: 더 높은 손익비 필요',risk:'위험: 신규 진입 보류',unknown:'자료 확인 전 보류'};
    const checks=[
      ['예측 검증',context.ai?.eligible?'시범 기준 통과 · 적은 검증 표본에 유의':context.ai?.reason||'선택 기간의 AI 검증 확인 필요',!!context.ai?.eligible],
      ['가격 위치',location,inside],
      ['시장 위험',marketNames[plan.market]||marketNames.unknown,['stable','watch'].includes(plan.market)],
      ['손익비','현재 '+rr+' / 필요한 기준 '+threshold,Number.isFinite(plan.rr)&&plan.rr>=threshold],
      ['추세 조건','현재 '+plan.ts+' / 진입 검토 기준 60',plan.ts>=60],
    ];
    const waiting=plan.blocks.length?plan.blocks.join(' · '):plan.ts<60?'추세 점수가 진입 검토 기준 60에 못 미칩니다.':!inside?'현재가가 관심 구간 밖에 있습니다. 가격 위치와 지지를 다시 확인하세요.':'수치 조건은 충족했지만 실제 지지 유지와 최신 공시를 확인해야 합니다.';
    const trigger=!hasZone?'자료가 갱신된 뒤 관심 구간을 확인하세요.':inside?'관심 구간 안입니다. 아래 미충족 조건이 해결됐는지 먼저 확인하세요.':price>plan.buyHigh?money(plan.buyHigh)+' 부근까지 조정될 때 다시 확인하세요. 도달만으로 매수 조건이 충족되지는 않습니다.':money(plan.buyLow)+' 위로 회복하는지 확인하세요. 하락 중 추가 매수를 권하는 신호가 아닙니다.';
    const invalid=plan.stop&&price>plan.stop?money(plan.stop)+' 아래로 종가가 내려가면 지지 가정을 재검토하세요. 현재가와의 차이는 약 '+pct((price-plan.stop)/price)+'%이며 손실 상한은 아닙니다.':plan.stop&&price<=plan.stop?'표시된 재평가 기준을 이미 이탈했습니다. 기존 지지 가정으로 신규 진입하지 말고 계획을 다시 확인하세요.':'유효한 재평가 가격을 계산하지 못했습니다. 손실 범위를 확인하기 전 신규 진입은 보류하세요.';
    return `<section class="nextSteps"><h3>지금 확인할 세 가지</h3><ol><li><b>지금 할 일 · 신규 매수 기준</b><span>${esc(plan.action)}. ${esc(plan.blocks[0]||'관심 가격대의 지지가 유지되는지 확인하세요.')}</span></li><li><b>언제 다시 확인할까?</b><span>${esc(trigger)}</span></li><li><b>예측이 틀렸다면?</b><span>${esc(invalid)} 시장 경고가 심해지거나 중요한 공시가 나오면 가격 도달 전에도 재평가하세요.</span></li></ol><details><summary>내가 기다려야 하는 구체적인 이유</summary><p>${esc(waiting)}</p><dl class="decisionChecks">${checks.map(([name,value,pass])=>`<div><dt>${esc(name)}</dt><dd><b class="${pass?'infoText':'warnText'}">${pass?'조건 확인':'확인 필요'}</b> · ${esc(value)}</dd></div>`).join('')}</dl><p>가격 기준일 ${esc(context.asOf||'확인 필요')} · 일별 종가 기준입니다. 실시간 호가와 다를 수 있어요. 실적 일정·기업 공시는 아직 자동 진입 조건에 포함하지 않습니다. 보유 중인 주식의 매도 판단에는 매입가·비중·최초 계획도 필요합니다.</p></details><details><summary>처음 보는 용어 설명</summary><p><b>지지:</b> 과거 매수세가 나타났거나 이동평균이 위치한 참고 가격. 반드시 반등하는 가격은 아닙니다.<br><b>저항:</b> 상승 중 매도 압력이 나타날 수 있는 참고 가격.<br><b>손익비:</b> 관심 구간 상단에서 샀을 때, 목표까지의 이익 폭을 손절까지의 손실 폭으로 나눈 값.<br><b>변동성:</b> 가격이 흔들리는 크기. 상승 확률을 뜻하지 않습니다.<br><b>손절 기준:</b> 계획을 재평가할 가격이며 실제 체결 가격이나 최대 손실을 보장하지 않습니다.<br><b>관망:</b> 조건이 갖춰질 때까지 매수를 미루는 판단입니다.</p></details></section>`;
  }
  const api={inspect,panel,nextSteps,comparisonPanel,allPeriods,horizonPanel,chartEntry};if(typeof module!=='undefined')module.exports=api;else root.LearnedGuide=api;
})(typeof window!=='undefined'?window:globalThis);
