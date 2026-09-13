/* Frozen SEC study: report collection, model tests and replay as distinct results. */
(() => {
  'use strict';
  const target = document.getElementById('stockStudy');
  if (!target) return;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => Number.isFinite(value) ? value.toFixed(4) : '자료 없음';
  const percent = value => Number.isFinite(value) ? (100 * value).toFixed(1) + '%' : '자료 없음';
  const count = value => Number.isFinite(value) ? value.toLocaleString('ko-KR') : '자료 없음';
  const folder = 'research/experiments/2026-09-13/';
  const repo = 'https://github.com/bumblev95/S-P-500-/blob/main/' + folder;
  const link = (file, label) => '<a href="' + repo + file + '">' + label + '</a>';
  const asset = document.getElementById('assetClass');
  function visibility() { target.hidden = asset?.value === 'crypto'; }
  asset?.addEventListener('change', visibility);
  visibility();

  fetch(folder + 'summary.json', {cache: 'no-store'})
    .then(response => { if (!response.ok) throw Error('Report unavailable'); return response.json(); })
    .then(data => {
      if (data.schemaVersion !== 1 || data.status !== 'completed' || !data.verification?.passed || data.productionPromoted !== false) throw Error('Unexpected report state');
      const c = data.coverage, r = data.ranking, q = data.quarterly, v = data.verification;
      const base = r.models.find(m => m.key === r.selected);
      const quarterly = r.models.find(m => m.key === 'quarterlyRidge');
      const rows = r.models.map(m => '<tr' + (m.selected ? ' class="highlight"' : '') + '><th scope="row">' + esc(m.label) + (m.selected ? '<small>앞선 기간에서 선택</small>' : '') + '</th><td>' + number(m.earlierIc) + '</td><td>' + number(m.laterIc) + '</td></tr>').join('');
      const riskRows = data.calibration.map(m => '<tr><th scope="row">' + m.months + '개월</th><td>' + number(m.rawAuc) + '</td><td>' + number(m.legacyAuc) + '</td><td>' + number(m.monotoneAuc) + '</td><td>' + number(m.monotoneBrier) + ' / ' + number(m.priorBrier) + '</td></tr>').join('');
      target.innerHTML = '<span class="tag">SEC 수집 · 재학습 결과</span><h2 id="stockStudyTitle">SEC 업데이트와 추가 검증을 마쳤습니다</h2>' +
        '<p>실험 완료 ' + esc(data.completedAt.slice(0, 16).replace('T', ' ')) + ' UTC · ' + data.configurations + '개 설정 비교 · 기존 가격 전망 교체 조건 미충족.</p>' +
        '<div class="cards"><div>SEC 원문 수집<strong>' + c.secSourceIssuers + ' / ' + c.targetIssuers + '개 기업</strong>' + c.targetTickers + '개 주식 종류 · 연간 학습 지표 ' + c.annualUsableIssuers + '개 기업</div>' +
        '<div>추가 모델 검증<strong>완료 · 개선 미확인</strong>하락확률·1년 종목 순위·분기 실적 효과를 비교</div>' +
        '<div>메인 예측 적용<strong>교체 조건 미충족</strong>실적 수집 성공과 가격 예측력 개선은 별도 결과</div></div>' +
        '<p class="quality-note">분기 실적 추가 후 1년 종목 순위 상관계수는 <b>' + number(base.laterIc) + ' → ' + number(quarterly?.laterIc) + '</b>였습니다. ' + (q.fitted ? '이번 실험에서는 개선되지 않았습니다.' : '분기 실적 추가 학습 조건을 충족하지 못했습니다.') + ' 순위 상관계수는 가격 적중률이나 투자 수익률이 아닙니다.</p>' +
        '<details><summary>종목 순위 비교와 해석</summary><p>앞선 8개 시작일에서 모델을 선택한 뒤, 후반 ' + r.dates + '개 시작일의 ' + count(r.rows) + '개 종목·시점을 평가했습니다.</p>' +
        '<div class="scroll"><table><caption>1년 종목 순위 · 날짜 평균 상관계수(IC)</caption><thead><tr><th scope="col">방법</th><th scope="col">앞선 기간</th><th scope="col">후반 기간</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '<p>상관계수는 −1~1이며 클수록 예측 순서와 실제 수익률 순서가 비슷합니다. 선택 모델의 모멘텀 대비 차이 구간은 ' + number(r.uncertainty[0]) + '~' + number(r.uncertainty[1]) + '로 0을 포함합니다. 8개 날짜를 재표집한 참고 구간이므로 안정적인 우위를 확인한 결과로 해석하지 않습니다.</p>' +
        '<p>현재 S&P 500 구성 기업의 과거를 사용했으며, 상장폐지 기업과 당시 구성 종목을 복원하지 못한 생존 편향이 남습니다. 이미 검토한 과거 기간을 재사용한 연구입니다.</p></details>' +
        '<details><summary>하락확률 보정은 좋아졌나요?</summary><p>기존 보정에서 하락 위험의 순서 정보가 약해졌습니다. 순서를 유지하는 보정도 과거 하락 빈도 기준을 안정적으로 넘지 못했습니다. 6개월과 1년 모두 적용 조건 미충족입니다.</p>' +
        '<div class="scroll"><table><caption>하락 구별과 확률 오차</caption><thead><tr><th scope="col">기간</th><th scope="col">보정 전 AUC</th><th scope="col">기존 보정 AUC</th><th scope="col">순서 유지 AUC</th><th scope="col">보정 / 기준 Brier</th></tr></thead><tbody>' + riskRows + '</tbody></table></div>' +
        '<p>AUC는 0.5가 무작위 구별 수준입니다. Brier는 확률 오차이며 작을수록 좋습니다. 표의 순서 유지 보정은 과거 8개 완료 날짜를 사용한 설정이며, 앞선 구간에서 선택 조건을 통과한 후보는 없었습니다.</p></details>' +
        '<details><summary>어디까지 수집·검증했나요?</summary><p>SEC 원문 ' + c.secSourceIssuers + '개 기업, 기존 연간 지표 ' + c.annualUsableIssuers + '개 기업, 가격 이력 ' + c.priceIssuers + '개 기업입니다. 기업 원문을 확보해도 모든 과거 분기에 필요한 항목이 있는 것은 아닙니다.</p>' +
        '<p>분기 매출 증가율·순이익률·현금흐름률을 모두 확보한 표본은 앞선 기간 ' + percent(c.completeQuarterlyCoverage?.earlier) + ', 후반 기간 ' + percent(c.completeQuarterlyCoverage?.later) + '입니다. NVDA·MSFT 공식 발표 ' + c.releaseChecks.matched + '건을 대조했고 ' + (c.releaseChecks.unavailable || 0) + '건은 대조 자료가 부족했습니다. 다른 기업과 현금흐름 전체를 개별 발표문으로 대조한 것은 아닙니다.</p>' +
        '<p>누적 현금흐름은 분기 차분으로 복원하고 공시일 이후에만 사용합니다. 수정 공시와 서로 다른 공시의 차분이 포함될 수 있으며, 과거 시점별 원본을 보증하는 데이터셋은 아닙니다. 과거 주식 수·주가 분할 기준을 맞출 자료가 부족해 밸류에이션 추가 실험은 실행하지 않았습니다.</p>' +
        '<p><b>순위 모델 재현 검사 통과:</b> ' + count(v.rows) + '개 예측의 보고 수치를 재계산했습니다. ' + esc(v.replayOrigin) + ' 이후 자료를 제거하고 ' + v.replayRows + '개 종목의 네 모델을 다시 학습한 예측값 최대 차이는 ' + v.maxDifference + '입니다. 가격 파일 ' + v.priceFiles + '개·실제 수익률 ' + count(v.targets) + '개도 원래 입력과 일치했습니다.</p>' +
        '<p>연구용 점수 ' + data.prospective.issuers + '개 기업분을 ' + esc(data.prospective.issuedAt.slice(0, 16).replace('T', ' ')) + ' UTC에 기록했습니다. 앞으로 252거래일 결과는 아직 확정되지 않았습니다.</p>' +
        '<nav aria-label="SEC 추가 검증 원자료">' + link('PROTOCOL.md', '고정 실험 설계') + link('E0-RESULTS.md', '확률 결과') + link('E1-RESULTS.md', '순위 결과') + link('E2-INCREMENT-RESULTS.md', '분기 실적 결과') + link('E3-RESULTS.md', '재현 검사') + '</nav></details>';
    })
    .catch(() => { target.innerHTML = '<h2 id="stockStudyTitle">SEC 추가 검증 결과</h2><p>완료 상태를 불러오지 못했습니다. 새로고침하거나 <a href="' + repo + 'E3-RESULTS.md">검증 기록</a>을 확인해 주세요.</p>'; });
})();
