# 하락 포착 후보와 낮은 오차 후보의 결합 연구

생성: 2026-10-04T04:33:44.242002+00:00 · 프로토콜 등록: 2026-10-04T04:28:20.473516+00:00

웹 화면·서비스 AI·순위·운용 정책을 변경하지 않았습니다. 앞서 검토한 동일 과거 자료를 다시 사용한 탐색 결과입니다. 후보도 앞선 실험을 보고 정했으므로 새로운 미검토 외부표본이나 실전 검증이 아닙니다.

가설 A는 예측값 평균·과거 오차 최소 조합·방향을 고려한 조합, 가설 B는 하락 점수로 비중 조절·과거 성적 조건을 만족할 때만 하락 후보로 전환하는 조합입니다. 모든 비중과 전환 문턱은 해당 기준일 이전에 결과가 확정된 외부표본 예측으로만 정합니다.

최종 방향은 결합한 수익률 자체의 부호(±2% 중립)를 평가합니다. 분류 점수에 맞춰 수익률의 부호를 덮어쓰지 않습니다. 하락 전문가의 값은 과거 실제 하락 표본에서 학습한 조건부 수익률입니다.

## 6개월

동일 표본 4417개 · 9개 기준일. 항상 상승 적중률 56.10%.

| 조합 | 가격 MAPE % | 수익률 MAE %p | 방향 적중 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % | 잘못된 하락 경고율 % |
|---|---:|---:|---:|---:|---:|---:|---:|
| 가격 불변 | 16.70 | 18.51 | 8.51 | 0.00 | 0.00 | — | 0.00 |
| 가격 패턴 | 16.99 | 18.18 | 51.12 | 90.11 | 0.06 | 20.00 | 0.14 |
| 공동 분포 단독 | 18.84 | 19.50 | 54.74 | 90.27 | 11.58 | 38.43 | 10.16 |
| 단순 50:50 | 17.71 | 18.63 | 51.21 | 89.10 | 0.26 | 19.05 | 0.60 |
| 과거 오차 최소 조합 | 17.89 | 19.01 | 37.97 | 63.84 | 0.13 | 40.00 | 0.11 |
| 방향·오차 조건 조합 | 17.89 | 19.01 | 37.97 | 63.84 | 0.13 | 40.00 | 0.11 |
| 하락 점수 가중 조합 | 17.18 | 18.99 | 24.27 | 22.92 | 21.88 | 32.36 | 25.05 |
| 조건 충족 시 하락 후보 전환 | 17.89 | 19.01 | 37.97 | 63.84 | 0.13 | 40.00 | 0.11 |

MAPE는 실제 미래 가격 대비 상대 오차입니다. 수익률 MAE는 예측 수익률과 실제 수익률의 차이(%p)입니다. 두 오차는 기준일별 평균을 동일 가중합니다. 방향 포착·경고 지표는 같은 전체 표본 기준입니다. 잘못된 하락 경고율은 실제 하락이 아닌 표본 중 하락으로 잘못 경고한 비율입니다.

공동 분포 단독의 방향은 클래스 점수 argmax이며 수익률 중앙값의 부호와 다를 수 있습니다. 결합 후보는 최종 값의 부호로 평가하므로 단독 방향 수치만 비교하면 안 됩니다. 단독 수익률 부호 적중률: 46.16%.

가격 패턴과 공동 분포의 로그 오차 상관 0.978; 공동 분포가 더 낮은 가격 오차를 낸 비중 40.68%.

미래 정답을 알고 매 표본 더 좋은 둘 중 하나를 고른 비현실적 참고 오차 15.37%. 이는 두 끝점 중 선택하는 미래 정보 기반 참고값이며, 중간 비중까지 허용한 최저 오차 경계나 실행 가능한 전략이 아닙니다.

- 단순 50:50: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, downRecall, downPrecision, directionEvidence, prospective`.
- 과거 오차 최소 조합: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective`.
- 방향·오차 조건 조합: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective`.
- 하락 점수 가중 조합: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, upRecall, downRecall, downPrecision, directionEvidence, prospective`.
- 조건 충족 시 하락 후보 전환: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective`.

과거 성적 조건이 안 맞을 때의 대체 경로도 제외하지 않고 전체 표본에 포함했습니다.

- error: selected_on_matured_oos 9개 기준일
- joint: infeasible_guard_use_error_blend 9개 기준일
- route: infeasible_guard_use_error_blend 9개 기준일

참고 분류기의 Brier 0.6761, 당시 이전 결과 비율 기준 0.5719. 숫자 결합 후보에 이 분류기의 확률을 그대로 붙이지 않았습니다. 확률 신뢰도는 results.json의 하락 점수 구간별 실제 하락 비율도 확인해야 합니다.

## 1년

동일 표본 3860개 · 8개 기준일. 항상 상승 적중률 66.09%.

| 조합 | 가격 MAPE % | 수익률 MAE %p | 방향 적중 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % | 잘못된 하락 경고율 % |
|---|---:|---:|---:|---:|---:|---:|---:|
| 가격 불변 | 21.98 | 27.89 | 5.70 | 0.00 | 0.00 | — | 0.00 |
| 가격 패턴 | 22.46 | 26.69 | 61.32 | 91.81 | 1.93 | 20.79 | 2.89 |
| 공동 분포 단독 | 24.17 | 27.88 | 55.62 | 74.01 | 23.78 | 26.48 | 25.95 |
| 단순 50:50 | 22.93 | 26.87 | 57.02 | 84.01 | 2.02 | 42.31 | 1.08 |
| 과거 오차 최소 조합 | 22.79 | 28.15 | 36.35 | 49.90 | 6.52 | 30.08 | 5.95 |
| 방향·오차 조건 조합 | 22.79 | 28.15 | 36.35 | 49.90 | 6.52 | 30.08 | 5.95 |
| 하락 점수 가중 조합 | 23.10 | 28.63 | 37.64 | 44.41 | 25.53 | 26.05 | 28.47 |
| 조건 충족 시 하락 후보 전환 | 22.79 | 28.15 | 36.35 | 49.90 | 6.52 | 30.08 | 5.95 |

MAPE는 실제 미래 가격 대비 상대 오차입니다. 수익률 MAE는 예측 수익률과 실제 수익률의 차이(%p)입니다. 두 오차는 기준일별 평균을 동일 가중합니다. 방향 포착·경고 지표는 같은 전체 표본 기준입니다. 잘못된 하락 경고율은 실제 하락이 아닌 표본 중 하락으로 잘못 경고한 비율입니다.

공동 분포 단독의 방향은 클래스 점수 argmax이며 수익률 중앙값의 부호와 다를 수 있습니다. 결합 후보는 최종 값의 부호로 평가하므로 단독 방향 수치만 비교하면 안 됩니다. 단독 수익률 부호 적중률: 53.42%.

가격 패턴과 공동 분포의 로그 오차 상관 0.947; 공동 분포가 더 낮은 가격 오차를 낸 비중 42.88%.

미래 정답을 알고 매 표본 더 좋은 둘 중 하나를 고른 비현실적 참고 오차 19.19%. 이는 두 끝점 중 선택하는 미래 정보 기반 참고값이며, 중간 비중까지 허용한 최저 오차 경계나 실행 가능한 전략이 아닙니다.

- 단순 50:50: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, downRecall, directionEvidence, prospective`.
- 과거 오차 최소 조합: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective`.
- 방향·오차 조건 조합: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective`.
- 하락 점수 가중 조합: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective`.
- 조건 충족 시 하락 후보 전환: 과거 조건 미통과; 미통과 `priceError, returnError, tail, returnTail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, directionEvidence, prospective`.

과거 성적 조건이 안 맞을 때의 대체 경로도 제외하지 않고 전체 표본에 포함했습니다.

- error: selected_on_matured_oos 8개 기준일
- joint: infeasible_guard_use_error_blend 8개 기준일
- route: infeasible_guard_use_error_blend 8개 기준일

참고 분류기의 Brier 0.6099, 당시 이전 결과 비율 기준 0.5016. 숫자 결합 후보에 이 분류기의 확률을 그대로 붙이지 않았습니다. 확률 신뢰도는 results.json의 하락 점수 구간별 실제 하락 비율도 확인해야 합니다.

## 해석과 후속 연구

- 단순 평균은 오차를 줄이면서도 하락 신호를 약화시킬 수 있고, 하락 점수만 강조하면 잘못된 경고가 늘 수 있습니다. 둘 중 한 항목만 좋아진 결과는 전체 개선으로 인정하지 않습니다.
- 현재 기업 구성으로 과거를 평가한 생존 편향, 수정 가격·공시 자료의 한계, 적은 시장 기준일과 기준일 간 상관이 남아 있습니다. 동일 기준일에는 CIK당 한 표본만 사용한 입력임을 검사했습니다.
- 이 연구의 가격 패턴 기준은 웹 서비스 모델과 다릅니다. 이번 결과로 APP 또는 현재 매도 Top 3를 정당화하거나 서비스 AI보다 우수하다고 주장하지 않습니다.
- 조합 방법·그리드·조건을 결과 확인 후 바꾸지 않았으며 후보 선택·자동 승격은 없습니다. 미래 발행 후 별도 관측이 필요합니다.
- 다음 단계는 오류가 덜 겹치는 시장/종목 고유 강도 입력을 보강하고, 조건별 수익률 크기를 학습하는 조합을 별도 프로토콜에서 비교합니다. 기간 중 낙폭 포착은 6개월·1년 종료 수익률과 별도 평가합니다.

## 근거 자료

- [예측 결합의 방법과 한계: Wang, Hyndman, Li, Kang](https://arxiv.org/abs/2205.04216)
- [외부표본 예측을 이용한 스태킹과 과적합 위험](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.StackingRegressor.html)
- [Adaptive Mixtures of Local Experts](https://www.cs.toronto.edu/~hinton/absps/jjnh91.pdf)
- [확률 교정과 신뢰도 점검](https://scikit-learn.org/stable/modules/calibration.html)

위 자료는 결합 방법의 연구 근거입니다. 이 종목·기간에서의 성능 보장은 아닙니다.

재현: `python scripts/research_indicator_blends.py` · 검사: `python scripts/test_indicator_blends.py`
