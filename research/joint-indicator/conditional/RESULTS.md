# 수익률 오차 직접 학습과 방향별 크기 연구

생성: 2026-10-04T05:02:44.393613+00:00 · 등록: 2026-10-04T04:57:33.894195+00:00

두 가설·네 후보와 동일 구조 제곱오차 대조군을 실행했습니다. 같은 과거 외부표본 자료를 다시 본 탐색이며 새 실전 검증이 아닙니다. 웹 화면·서비스 AI·순위·운용 정책은 변경하지 않았습니다.

가설 A는 평균 수익률 차이(MAE) 또는 미래 실제 가격 대비 오차(MAPE)를 직접 줄이도록 학습합니다. 가설 B는 상승·횡보·하락별 크기를 별도로 학습한 뒤 기존 분류 점수와 결합합니다. 숫자 예측의 부호를 덮어쓰거나 상승·하락 개수를 임의로 맞추지 않습니다.

기존 외부표본 예측·공시 방향 점수와 알려진 시장 상황을 입력으로 재사용합니다. 새로운 원시 가격·업종 강도·기간 중 낙폭 입력은 추가하지 않았습니다. 따라서 학습 방법을 바꾼 실험이며 새로운 정보 확보의 효과를 검증한 실험이 아닙니다.

## 6개월

동일 4417개 표본·9개 기준일. 항상 상승 적중 56.10%.

| 방법 | 가격 MAPE % | 수익률 MAE %p | 최종 수익률 방향 적중 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % |
|---|---:|---:|---:|---:|---:|---:|
| 가격 불변 | 16.70 | 18.51 | 8.51 | 0.00 | 0.00 | — |
| 가격 패턴 | 16.99 | 18.18 | 51.12 | 90.11 | 0.06 | 20.00 |
| 기존 공동 분포 | 18.84 | 19.50 | 46.16 | 90.27 | 11.58 | 38.43 |
| 동일 구조 제곱오차 대조군 | 19.49 | 19.53 | 55.17 | 98.02 | 0.00 | — |
| 수익률 절대오차 직접 학습 | 18.08 | 18.53 | 52.57 | 92.62 | 0.00 | — |
| 가격 비율오차 직접 학습 | 17.68 | 18.56 | 48.90 | 84.87 | 0.38 | 54.55 |
| 방향별 크기 · 수익률 오차 | 21.10 | 20.88 | 46.16 | 77.04 | 3.90 | 35.06 |
| 방향별 크기 · 가격 오차 | 20.71 | 21.12 | 38.15 | 56.26 | 12.28 | 37.35 |

오차는 날짜별 평균을 동일 가중합니다. 방향 지표는 같은 전체 표본을 사용하며 ±2% 중립입니다. 공동 분포 참조의 상승·하락 포착은 클래스 argmax이고 나머지는 최종 수익률 부호이므로 그 두 정의를 같은 방향 성적으로 섞지 않습니다.

- 수익률 절대오차 직접 학습: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective`.
- 가격 비율오차 직접 학습: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, directionEvidence, prospective`.
- 방향별 크기 · 수익률 오차: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective`.
- 방향별 크기 · 가격 오차: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective`.

| 후보 | 가격 패턴 대비 수익률 MAE 개선 %p | 날짜 묶음 참고 구간 %p |
|---|---:|---:|
| 수익률 절대오차 직접 학습 | -0.34 | -1.61 ~ 0.80 |
| 가격 비율오차 직접 학습 | -0.38 | -1.15 ~ 0.30 |
| 방향별 크기 · 수익률 오차 | -2.70 | -5.29 ~ -0.42 |
| 방향별 크기 · 가격 오차 | -2.94 | -5.02 ~ -0.85 |

양수이면 후보 오차가 작습니다. 이미 본 적은 날짜들을 재표집한 참고 구간이며 시장 기준일 간 독립성을 보장하지 않습니다.

- 미래 정답 방향을 알고 크기 전문가를 고르는 비실행 진단 방향별 크기 · 수익률 오차: 수익률 MAE 11.26%p. 실제 후보 성과·선택·승격에 사용하지 않았습니다.
- 미래 정답 방향을 알고 크기 전문가를 고르는 비실행 진단 방향별 크기 · 가격 오차: 수익률 MAE 11.25%p. 실제 후보 성과·선택·승격에 사용하지 않았습니다.
- 클래스 표본 부족으로 풀링 대체한 기준일: 0. 모든 기준일을 성적에 포함했습니다.

참고 분류기의 Brier 0.6761 / 과거 클래스 비율 기준 0.5719. 새로운 숫자 후보의 확률 성적으로 제시하지 않습니다.

## 1년

동일 3860개 표본·8개 기준일. 항상 상승 적중 66.09%.

| 방법 | 가격 MAPE % | 수익률 MAE %p | 최종 수익률 방향 적중 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % |
|---|---:|---:|---:|---:|---:|---:|
| 가격 불변 | 21.98 | 27.89 | 5.70 | 0.00 | 0.00 | — |
| 가격 패턴 | 22.46 | 26.69 | 61.32 | 91.81 | 1.93 | 20.79 |
| 기존 공동 분포 | 24.17 | 27.88 | 53.42 | 74.01 | 23.78 | 26.48 |
| 동일 구조 제곱오차 대조군 | 27.86 | 29.03 | 66.11 | 99.96 | 0.00 | — |
| 수익률 절대오차 직접 학습 | 25.88 | 27.86 | 65.70 | 99.37 | 0.00 | — |
| 가격 비율오차 직접 학습 | 24.47 | 27.71 | 63.21 | 90.32 | 12.21 | 34.73 |
| 방향별 크기 · 수익률 오차 | 28.32 | 30.47 | 53.42 | 72.99 | 16.99 | 28.37 |
| 방향별 크기 · 가격 오차 | 27.42 | 30.90 | 50.28 | 64.80 | 25.44 | 25.65 |

오차는 날짜별 평균을 동일 가중합니다. 방향 지표는 같은 전체 표본을 사용하며 ±2% 중립입니다. 공동 분포 참조의 상승·하락 포착은 클래스 argmax이고 나머지는 최종 수익률 부호이므로 그 두 정의를 같은 방향 성적으로 섞지 않습니다.

- 수익률 절대오차 직접 학습: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective`.
- 가격 비율오차 직접 학습: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, downRecall, directionEvidence, prospective`.
- 방향별 크기 · 수익률 오차: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective`.
- 방향별 크기 · 가격 오차: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective`.

| 후보 | 가격 패턴 대비 수익률 MAE 개선 %p | 날짜 묶음 참고 구간 %p |
|---|---:|---:|
| 수익률 절대오차 직접 학습 | -1.17 | -6.43 ~ 3.57 |
| 가격 비율오차 직접 학습 | -1.02 | -4.95 ~ 2.38 |
| 방향별 크기 · 수익률 오차 | -3.78 | -9.69 ~ 2.22 |
| 방향별 크기 · 가격 오차 | -4.21 | -9.35 ~ 1.59 |

양수이면 후보 오차가 작습니다. 이미 본 적은 날짜들을 재표집한 참고 구간이며 시장 기준일 간 독립성을 보장하지 않습니다.

- 미래 정답 방향을 알고 크기 전문가를 고르는 비실행 진단 방향별 크기 · 수익률 오차: 수익률 MAE 17.12%p. 실제 후보 성과·선택·승격에 사용하지 않았습니다.
- 미래 정답 방향을 알고 크기 전문가를 고르는 비실행 진단 방향별 크기 · 가격 오차: 수익률 MAE 17.02%p. 실제 후보 성과·선택·승격에 사용하지 않았습니다.
- 클래스 표본 부족으로 풀링 대체한 기준일: 0. 모든 기준일을 성적에 포함했습니다.

참고 분류기의 Brier 0.6099 / 과거 클래스 비율 기준 0.5016. 새로운 숫자 후보의 확률 성적으로 제시하지 않습니다.

## 해석 제한과 근거

- 후보·입력·학습 목표·그리드·평가 구간을 실행 전 고정했으며 결과 후 튜닝은 없습니다. 통과 여부와 별개로 자동 승격·병합하지 않습니다.
- MAE와 MAPE는 다른 손실입니다. MAPE만 줄이면 작은 실제 가격에 더 큰 가중치가 생기므로 하락 포착·상승 포착·수익률 오차·잘못된 경고·큰 오차를 모두 봐야 합니다.
- 조건부 모델은 세 대표값으로 분포를 근사합니다. 그중 최적 값이라는 말은 그 근사와 손실 안에서의 의미이며 실제 미래 수익률 분포의 최적 예측이나 정확한 확률을 뜻하지 않습니다.
- 회귀 학습은 해당 기준일 전에 결과가 확정된 모든 표본을 사용하고, 분류기는 기존처럼 학습/교정 미래 구간을 제거합니다. 모델마다 같은 과거 결과를 다른 역할로 사용합니다.
- 현재 기업 구성의 생존 편향, 적은 시장 날짜와 상관, 수정 가격/공시의 한계가 남아 있습니다. 직접 웹 서비스 AI 우위나 현재 APP 매도 여부를 주장하지 않습니다.
- 미래 발행 후 관측과 거래비용을 검증하지 않았습니다. 종료 수익률 방향과 기간 중 하락 포착은 별도 목표입니다.

- [MAPE 회귀와 가중 절대오차: de Myttenaere 외](https://arxiv.org/abs/1605.02541)
- [공식 회귀 손실·표본 가중치 문서](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html)
- [MAE, RMSE, MAPE의 평가 차이](https://otexts.com/fpp3/accuracy.html)

재현: `python scripts/research_conditional_indicator.py` · 검사: `python scripts/test_conditional_indicator.py`
