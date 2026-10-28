# 잔차 모멘텀 횡단면 순위 보정 연구

사전 등록: 2026-10-14T01:15:43Z · 실행: 2026-10-14T01:20:30.758034+00:00

잔차수익률로 종목을 순위화하면 총수익률 모멘텀의 시변 시장요인 노출을 줄일 수 있다는 연구를 작은 고정 보정으로 검사했다. 결과를 본 뒤 계수나 문턱을 바꾸지 않았다.

## 126거래일

평가 9개 날짜, 4417행 · 결측 대체 13행 · 하락 보정 493행

| 방법 | 미래가격 MAPE % | 수익률 MAE %p | 방향 적중 % | 균형 방향 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % | 잘못된 경고율 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 가격 불변 | 16.70 | 18.51 | 8.52 | 33.33 | 0.00 | 0.00 | — | 0.00 |
| 가격 패턴 기준 | 16.98 | 18.17 | 50.85 | 32.05 | 89.70 | 0.06 | 24.72 | 0.11 |
| 단순 가격 추세 | 24.52 | 25.16 | 44.70 | 32.93 | 56.39 | 35.21 | 34.74 | 36.29 |
| 기존 상대강도 전문가 | 17.93 | 18.55 | 48.98 | 33.23 | 84.21 | 1.71 | 27.55 | 2.47 |
| 잔차순위 대칭 보정 | 17.00 | 18.19 | 45.48 | 32.09 | 78.36 | 0.13 | 18.10 | 0.32 |
| 잔차순위 하락 보정 | 16.98 | 18.26 | 47.63 | 32.87 | 80.66 | 3.31 | 29.21 | 4.41 |

- 잔차순위 대칭 보정: 미통과 priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective, falseWarnings; 가격패턴 로그오차 상관 0.998.
- 잔차순위 하락 보정: 미통과 priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective, falseWarnings; 가격패턴 로그오차 상관 0.998.

## 252거래일

평가 8개 날짜, 3860행 · 결측 대체 17행 · 하락 보정 324행

| 방법 | 미래가격 MAPE % | 수익률 MAE %p | 방향 적중 % | 균형 방향 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % | 잘못된 경고율 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 가격 불변 | 21.98 | 27.89 | 5.69 | 33.33 | 0.00 | 0.00 | — | 0.00 |
| 가격 패턴 기준 | 22.47 | 26.70 | 61.04 | 31.70 | 91.41 | 1.86 | 19.98 | 2.93 |
| 단순 가격 추세 | 40.33 | 44.90 | 50.66 | 33.13 | 63.72 | 28.92 | 26.42 | 31.65 |
| 기존 상대강도 전문가 | 25.66 | 27.38 | 66.09 | 33.33 | 100.00 | 0.00 | — | 0.00 |
| 잔차순위 대칭 보정 | 22.52 | 26.74 | 60.13 | 31.56 | 89.83 | 2.14 | 18.66 | 3.66 |
| 잔차순위 하락 보정 | 22.52 | 26.85 | 58.90 | 31.84 | 87.30 | 3.24 | 20.87 | 4.83 |

- 잔차순위 대칭 보정: 미통과 priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective, falseWarnings; 가격패턴 로그오차 상관 0.999.
- 잔차순위 하락 보정: 미통과 priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective, falseWarnings; 가격패턴 로그오차 상관 0.999.

## 판정

두 가설 모두 전체 조건 미통과이며 승격·후보 선택은 없다. 현재 구성종목·현재 업종·수정 가격을 쓴 이미 관찰된 과거 구간이라 탐색 결과일 뿐 새 실전 증거가 아니다.

보류율은 0%이고 결측은 가격패턴 기준으로 대체해 전체 표본에 포함했다. 숫자 예측이라 확률 성적은 해당 없으며 Brier/log loss를 만들지 않았다. 단기 진입·보유 및 비용·회전율·낙폭을 평가하지 않았으므로 매매 성과를 주장하지 않는다.

UI, 서비스 예측·순위, 실전·모의운용, 자동 승격 정책은 변경하지 않았다.

## 다음 연구

- 시점별 구성종목과 상장폐지 종목이 포함된 자료가 확보되기 전에는 같은 현재-universe 횡단면 보정을 반복 튜닝하지 않는다.
- 다음 비중복 후보는 12개월 고점까지의 장기 상승(HTP)과 고점 근접도(PTH)를 분리하거나, 새 발행 예측의 실제 관측이 쌓인 뒤 사전 고정 역할 전환을 검증한다.

재현: `PYTHONPATH=scripts python scripts/research_rank_tilt.py`

근거: [Residual Momentum (Journal of Empirical Finance, 2011)](https://doi.org/10.1016/j.jempfin.2011.01.003) · [Erasmus 저장본](https://repub.eur.nl/pub/22252)
