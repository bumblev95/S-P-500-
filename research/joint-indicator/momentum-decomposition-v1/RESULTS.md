# HTP·PTH 모멘텀 분해 연구

사전 등록: 2026-10-17T01:06:07Z · 실행: 2026-10-17T01:12:08.038561+00:00

12–1개월 모멘텀을 과거 고점 전 상승(HTP)과 고점 후 움직임(PTH)으로 분리했다. HTP 순위의 작은 대칭 보정과 HTP·PTH가 모두 상위 20%인 종목만 낮추는 희소 경계를 결과 확인 전 고정했다.

## 126거래일

9개 날짜 · 4408행 · 결측 대체 4행 · 희소 경계 227행

| 방법 | 미래가격 MAPE % | 수익률 MAE %p | 방향 적중 % | 균형 방향 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % | 잘못된 경고율 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 가격 불변 | 16.73 | 18.51 | 8.53 | 33.33 | 0.00 | 0.00 | — | 0.00 |
| 가격 패턴 기준 | 17.02 | 18.18 | 50.35 | 31.91 | 88.76 | 0.06 | 25.03 | 0.11 |
| 단순 126일 추세 | 24.55 | 25.18 | 44.79 | 33.02 | 56.45 | 35.40 | 34.85 | 36.33 |
| 총 모멘텀 순위 보정 | 17.06 | 18.22 | 44.73 | 31.44 | 77.08 | 0.26 | 24.96 | 0.42 |
| HTP 순위 보정 | 17.08 | 18.21 | 45.72 | 32.48 | 78.61 | 0.26 | 30.73 | 0.32 |
| HTP·PTH 과열 하락 경계 | 17.02 | 18.24 | 48.17 | 31.60 | 83.95 | 0.77 | 23.11 | 1.40 |

- HTP 순위 보정: 미통과 priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective, falseWarnings; 가격패턴 로그오차 상관 0.998.
- HTP·PTH 과열 하락 경계: 미통과 priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective, falseWarnings; 가격패턴 로그오차 상관 0.999.

## 252거래일

8개 날짜 · 3855행 · 결측 대체 9행 · 희소 경계 171행

| 방법 | 미래가격 MAPE % | 수익률 MAE %p | 방향 적중 % | 균형 방향 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % | 잘못된 경고율 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 가격 불변 | 22.06 | 28.02 | 5.68 | 33.33 | 0.00 | 0.00 | — | 0.00 |
| 가격 패턴 기준 | 22.57 | 26.84 | 61.11 | 31.57 | 91.57 | 1.77 | 20.21 | 2.75 |
| 단순 126일 추세 | 41.22 | 46.04 | 50.74 | 33.27 | 63.61 | 29.42 | 26.74 | 31.69 |
| 총 모멘텀 순위 보정 | 22.56 | 26.85 | 59.54 | 31.24 | 88.97 | 2.04 | 19.12 | 3.40 |
| HTP 순위 보정 | 22.58 | 26.82 | 60.49 | 31.79 | 90.53 | 1.67 | 19.33 | 2.74 |
| HTP·PTH 과열 하락 경계 | 22.57 | 26.89 | 60.06 | 31.49 | 89.79 | 1.95 | 20.57 | 2.97 |

- HTP 순위 보정: 미통과 priceError, returnError, tail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective; 가격패턴 로그오차 상관 0.999.
- HTP·PTH 과열 하락 경계: 미통과 priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective, falseWarnings; 가격패턴 로그오차 상관 0.999.

## 판정

두 후보 모두 전체 조건을 통과하지 못했으며 선택·승격하지 않는다. 동일 과거 결과를 다시 본 탐색으로 새 실전 증거가 아니다.

보류율은 0%이며 결측 대체도 전체 성적에 포함했다. 숫자 보정은 확률을 출력하지 않으므로 Brier·log loss는 해당 없음이다. 거래 체결·비용·회전율을 평가하지 않아 매매 성과를 주장하지 않는다.

현재 구성종목과 수정 조정가격 편향이 남고 PIT·상장폐지 생애주기 준비도는 0/34다. 논문의 횡단면 포트폴리오 수익을 재현하거나 이 장기 가격예측에 그대로 적용된다고 주장하지 않는다.

UI, 서비스 예측·순위, 실전·모의운용, 자동 승격 기준은 변경하지 않았다.
