# 시장·업종 상대 강도와 결합 연구

등록: 2026-10-07T01:23:40.712629+00:00 · 실행: 2026-10-07T01:30:49.930226+00:00

가설 A: 새 원시 가격으로 절대 추세와 시장·업종 상대 강도를 분리. 가설 B: 해당 전문가와 가격 패턴의 단순 평균·과거 확정 오차 조합·시장 약세 시 역할 전환. 결과 후 튜닝 없음.

최신 main의 가격·모델 자료가 이전 연구와 달라 새 기준값을 동일 표본으로 다시 계산했다. 과거 18개/16개 origin 집합은 그대로다. 새 실전 증거나 웹 서비스 AI와의 직접 우위 비교가 아니다.

## 126거래일

{'totalRows': 4417, 'usableRows': 4404, 'sectorRows': 4404, 'fallbackRows': 13} · 9개 날짜

| 방법 | 가격 MAPE % | 수익률 MAE %p | 방향 적중 % | 균형 방향 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % | 잘못된 경고율 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 가격 불변 | 16.70 | 18.51 | 8.52 | 33.33 | 0.00 | 0.00 | — | 0.00 |
| 가격 패턴 기준 | 16.98 | 18.17 | 50.85 | 32.05 | 89.70 | 0.06 | 24.72 | 0.11 |
| 단순 가격 추세 | 24.52 | 25.16 | 44.70 | 32.93 | 56.39 | 35.21 | 34.74 | 36.29 |
| 절대 추세 대조군 | 17.84 | 18.48 | 49.27 | 32.89 | 83.96 | 3.56 | 29.53 | 4.66 |
| 시장·업종 상대 강도 | 17.93 | 18.55 | 48.98 | 33.23 | 84.21 | 1.71 | 27.55 | 2.47 |
| 상대 강도 50:50 | 17.33 | 18.23 | 51.20 | 32.46 | 90.25 | 0.00 | 0.00 | 0.04 |
| 과거 확정 오차 조합 | 17.47 | 18.49 | 51.14 | 32.21 | 90.26 | 0.00 | 0.00 | 0.11 |
| 시장 약세 시 역할 전환 | 16.99 | 18.19 | 50.62 | 31.99 | 88.90 | 0.70 | 26.16 | 1.08 |

항상 상승 적중률 56.05%. 로그 오차 상관 0.982. 수익률 부호와 방향은 동일 정의(±2% 중립).

- 시장·업종 상대 강도: 미통과 항목 priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective, falseWarnings, absoluteControl.
- 상대 강도 50:50: 미통과 항목 priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective.
- 과거 확정 오차 조합: 미통과 항목 priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective, absoluteControl.
- 시장 약세 시 역할 전환: 미통과 항목 priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective, falseWarnings.

## 252거래일

{'totalRows': 3860, 'usableRows': 3843, 'sectorRows': 3811, 'fallbackRows': 17} · 8개 날짜

| 방법 | 가격 MAPE % | 수익률 MAE %p | 방향 적중 % | 균형 방향 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % | 잘못된 경고율 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 가격 불변 | 21.98 | 27.89 | 5.69 | 33.33 | 0.00 | 0.00 | — | 0.00 |
| 가격 패턴 기준 | 22.47 | 26.70 | 61.04 | 31.70 | 91.41 | 1.86 | 19.98 | 2.93 |
| 단순 가격 추세 | 40.33 | 44.90 | 50.66 | 33.13 | 63.72 | 28.92 | 26.42 | 31.65 |
| 절대 추세 대조군 | 25.70 | 27.42 | 66.07 | 33.32 | 99.96 | 0.00 | — | 0.00 |
| 시장·업종 상대 강도 | 25.66 | 27.38 | 66.09 | 33.33 | 100.00 | 0.00 | — | 0.00 |
| 상대 강도 50:50 | 23.40 | 26.27 | 65.78 | 33.45 | 99.46 | 0.00 | 0.00 | 0.11 |
| 과거 확정 오차 조합 | 23.49 | 26.73 | 64.92 | 32.83 | 98.03 | 0.47 | 14.84 | 1.05 |
| 시장 약세 시 역할 전환 | 22.47 | 26.70 | 61.04 | 31.70 | 91.41 | 1.86 | 19.98 | 2.93 |

항상 상승 적중률 66.09%. 로그 오차 상관 0.968. 수익률 부호와 방향은 동일 정의(±2% 중립).

- 시장·업종 상대 강도: 미통과 항목 priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective.
- 상대 강도 50:50: 미통과 항목 priceError, returnError, tail, dateConsistency, direction, returnDirection, downRecall, downPrecision, directionEvidence, prospective.
- 과거 확정 오차 조합: 미통과 항목 priceError, returnError, tail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective.
- 시장 약세 시 역할 전환: 미통과 항목 priceError, returnError, tail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective.

## 해석과 재현

- 표의 오차·방향·포착·경고는 날짜별 동일 가중. 기존 비교용 전체 표본 단순 집계도 pooledAllRows에 별도 보존했다. 큰 오차·날짜별 결과·시장 상황별 성적은 results.json에 저장했다. 보류율0%; 결측 대체 행도 전체 성적에 포함했다.
- 숫자 전문가·결합은 확률을 출력하지 않으므로 Brier·logloss는 해당 없음으로 기록했다. 미교정 점수를 확률로 쓰지 않았다.
- 현재 구성 종목/업종과 수정된 조정가격을 사용한 생존·분류·자료 수정 편향이 남는다. XLC·XLRE의 상장 전 자료를 만들어내지 않았다. 잔차 강도 논문의 방법을 그대로 재현하거나 그 수익을 달성했다고 주장하지 않는다.
- 학습·비중 선택은 각 origin 전 결과 확정 표본만 사용. 같은 horizon 결과 구간의 겹침과 CIK/date 중복을 검증했다. 적은 날짜와 시장 상관으로 통계 신뢰는 제한된다.
- 단기 진입·보유 규칙과 별도인 장기 예측 연구. 거래 체결·비용·회전율·낙폭을 검증하지 않아 매매 성과를 주장하지 않는다.
- 새 발행 기록은 별도로 보존해야 한다. 이번 main의 최신 전망 origin은 2026-10-05로 발행 시점과 다르므로 소급 예측을 새 발행으로 넣지 않았다.
- UI·서비스 예측·순위·실전/모의운용·승격 정책 변경 없음. 후보 선택·자동 병합 없음.
- 다음 연구: 시점별 구성·업종 및 상장폐지 포함 자료 확보; 종료 수익률과 기간 중 낙폭 목표 분리. 새 후보가 원시 가격을 사용해도 오차 상관이 낮아지지 않으면 평균/스태킹 반복을 우선하지 않는다.

재현: `python scripts/research_relative_blends.py` · 입력 수집: `python scripts/collect_relative_inputs.py` · 검증: `python scripts/test_relative_blends.py`

근거: [Residual Momentum, 2011](https://repub.eur.nl/pub/22252) · [공식 회귀 문서](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html)
