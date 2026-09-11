(function(root){
  'use strict';
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pct=x=>Number.isFinite(x)?(x*100).toFixed(2)+'%':'—';
  const names={noChange:'가격 불변',trend:'기존 추세',original:'현재 AI',relativeMAE:'상대오차 학습 AI',halfBlend:'상대오차 AI + 가격 불변 50%'};
  function panel(data,h,learned){
    const r=data?.horizons?.[h];
    if(!r||r.status!=='research')return '<details><summary>오차를 안정적으로 줄였을까?</summary><p>안정성 비교 자료를 준비 중입니다.</p></details>';
    const checkNames={enoughDates:'평가 시점 4개 이상',average:'평균 오차 개선',tail:'큰 오차 악화 없음',consistency:'여러 시점에서 개선',direction:'단순 상승 예상 이상의 방향 일치'};
    return `<details class="stabilityPanel"><summary>오차를 안정적으로 줄였을까? · ${r.passed?'연구 기준 통과':'추가 검증 필요'}</summary><p>앞선 ${r.selectionDates.length}개 시점에서 방법을 선택한 뒤, 뒤의 ${r.evaluationDates.length}개 시점에서 평가했습니다. 아래 결과는 전체 수집 종목의 같은 시험 표본 비교입니다.</p><p>앞선 성적으로 선택한 방법: <b>${esc(names[r.chosen]||r.chosen)}</b>. 뒤의 결과를 보고 우승 방법을 다시 고르지 않습니다.</p><div class="marketTable"><table class="comparisonTable"><thead><tr><th>방법</th><th>평균 가격 오차</th><th>큰 오차</th><th>±10% 안</th></tr></thead><tbody>${Object.entries(r.evaluation).map(([k,m])=>`<tr><td>${esc(names[k]||k)}${k===r.chosen?' · 사전 선택':''}</td><td>${pct(m.mape)}</td><td>${pct(m.p90)}</td><td>${pct(m.within10)}</td></tr>`).join('')}</tbody></table></div><p>가격 오차 = |예상 가격 − 실제 가격| ÷ 실제 가격. 앞의 수익률 오차(%p)와 다른 단위입니다. 큰 오차는 가격 오차의 90백분위이며 최대 손실이 아닙니다. ±10% 안은 과거 예측이 그 범위에 들어온 비율입니다.</p><p>${Object.entries(r.checks).map(([k,v])=>`${esc(checkNames[k]||k)}: ${v?'충족':'미충족'}`).join(' · ')}</p><p>선택 단계에서는 시점별 평균 가격 오차와 큰 오차를 함께 줄이는 방법을 골랐습니다. 연구 기준은 평균·큰 오차·시점별 일관성·방향을 함께 확인합니다. 소수 시점과 종목 간 상관 때문에 안정적 개선을 확정할 수 없습니다.</p><p>최종 평가 시작 ${esc(r.evaluationStart)} · 선택에 쓴 결과 마지막 날짜 ${esc(r.selectionTargetThrough)}. 이 과거 구간은 이전 연구에서 검토된 적이 있어 실제 발표 후 검증을 대신하지 않습니다. 현재 차트의 모델과 매수 기준은 자동 변경하지 않습니다.</p><p>자료 ${esc(data.generatedAt?.slice(0,10))}${data.sourceGeneratedAt!==learned?.generatedAt?' · 현재 모델 갱신보다 이전 분석 결과':''}</p></details>`;
  }
  const api={panel};if(typeof module!=='undefined')module.exports=api;else root.StabilityPanel=api;
})(typeof window!=='undefined'?window:globalThis);
