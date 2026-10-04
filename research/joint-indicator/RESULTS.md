# 상승·하락 방향과 수익률 공동 연구

생성: 2026-10-04T04:02:15.336804+00:00 · 기준 커밋: `c67f12f1242c85bb570561ed5fed9d635c8afd8e`

웹 화면·서비스 모델·매수/매도 순위를 변경하지 않은 연구입니다. 기존 연구의 과거 외부표본 예측을 입력으로 재사용한 탐색이며, 새로운 실전 검증 결과가 아닙니다.

동일한 분포에서 상승·횡보·하락 점수와 수익률 중앙값을 계산했습니다. 방향은 가장 큰 클래스 점수이며, 중앙값의 부호와 다를 수 있어 두 방향 성적을 각각 평가합니다. 종목의 실제 당일 수익률을 입력하지 않습니다.

## 6개월

동일 표본 4417개 · 9개 날짜. 항상 상승 기준 56.10%.

| 방법 | 날짜별 가격 오차 | 방향 적중 | 수익률 부호 적중 | 상승 포착 | 하락 포착 | 하락 경고 적중 |
|---|---:|---:|---:|---:|---:|---:|
| 가격 불변 | 16.70% | 8.51% | 8.51% | 0.00% | 0.00% | — |
| 가격 패턴 | 16.99% | 51.12% | 51.12% | 90.11% | 0.06% | 20.00% |
| 기존 균형 연구 | 17.83% | 40.07% | 40.07% | 62.35% | 11.26% | 18.72% |
| 기존 방향 분류 | 18.21% | 52.73% | 43.45% | 89.02% | 7.87% | 28.47% |
| 기존 SEC 변화 분류 | 17.99% | 53.52% | 42.40% | 92.57% | 4.48% | 26.02% |
| 공동 분포 · 로지스틱 | 18.84% | 54.74% | 46.16% | 90.27% | 11.58% | 38.43% |
| 공동 분포 · 균형 로지스틱 | 18.83% | 54.86% | 44.53% | 93.34% | 7.04% | 35.60% |
| 공동 분포 · 트리 | 18.87% | 50.24% | 45.82% | 80.06% | 15.04% | 29.52% |

가격 오차는 미래 실제 가격 대비 MAPE입니다. 방향은 ±2%를 중립으로 분류합니다. 하락 경고 적중률과 하락 포착률은 서로 다른 지표입니다.

- 공동 분포 · 로지스틱: 과거 조건 미통과; 미통과 `priceError, tail, dateConsistency, direction, returnDirection, downRecall, downPrecision, probability, directionEvidence, prospective`.
- 공동 분포 · 균형 로지스틱: 과거 조건 미통과; 미통과 `priceError, tail, dateConsistency, direction, returnDirection, downRecall, downPrecision, probability, directionEvidence, prospective`.
- 공동 분포 · 트리: 과거 조건 미통과; 미통과 `priceError, tail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, probability, directionEvidence, prospective`.

후반 성적을 보고 후보나 문턱을 바꾸지 않았습니다. 후보 선택·자동 승격은 없습니다.

## 1년

동일 표본 3860개 · 8개 날짜. 항상 상승 기준 66.09%.

| 방법 | 날짜별 가격 오차 | 방향 적중 | 수익률 부호 적중 | 상승 포착 | 하락 포착 | 하락 경고 적중 |
|---|---:|---:|---:|---:|---:|---:|
| 가격 불변 | 21.98% | 5.70% | 5.70% | 0.00% | 0.00% | — |
| 가격 패턴 | 22.46% | 61.32% | 61.32% | 91.81% | 1.93% | 20.79% |
| 기존 균형 연구 | 22.73% | 66.09% | 66.09% | 100.00% | 0.00% | — |
| 기존 방향 분류 | 23.08% | 66.06% | 65.21% | 99.96% | 0.00% | 0.00% |
| 기존 SEC 변화 분류 | 22.97% | 66.09% | 62.90% | 100.00% | 0.00% | — |
| 공동 분포 · 로지스틱 | 24.17% | 55.62% | 53.42% | 74.01% | 23.78% | 26.48% |
| 공동 분포 · 균형 로지스틱 | 24.16% | 55.85% | 53.50% | 74.36% | 23.78% | 26.76% |
| 공동 분포 · 트리 | 24.58% | 56.50% | 50.80% | 82.71% | 6.52% | 13.47% |

가격 오차는 미래 실제 가격 대비 MAPE입니다. 방향은 ±2%를 중립으로 분류합니다. 하락 경고 적중률과 하락 포착률은 서로 다른 지표입니다.

- 공동 분포 · 로지스틱: 과거 조건 미통과; 미통과 `priceError, tail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, probability, directionEvidence, prospective`.
- 공동 분포 · 균형 로지스틱: 과거 조건 미통과; 미통과 `priceError, tail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, probability, directionEvidence, prospective`.
- 공동 분포 · 트리: 과거 조건 미통과; 미통과 `priceError, tail, dateConsistency, direction, returnDirection, balancedDirection, downRecall, downPrecision, probability, directionEvidence, prospective`.

후반 성적을 보고 후보나 문턱을 바꾸지 않았습니다. 후보 선택·자동 승격은 없습니다.

## 제한과 다음 연구

- 현재 구성 기업을 과거에 적용한 생존 편향이 남아 있습니다.
- 같은 날짜의 종목들은 독립된 시장 상황이 아닙니다. 날짜를 묶어 방향 개선 차이의 참고 구간을 계산했으며, 날짜 간 독립도 보장되지 않습니다.
- 이 비교의 가격 패턴 기준은 기존 연구 모델입니다. 다른 표본을 사용하는 웹 서비스 AI와의 직접 우위 비교가 아닙니다.
- 분포 범위는 연구 추정치입니다. 미래 포함 확률이나 수익을 보장하지 않습니다.
- 상승·하락장 및 고변동장 성적을 분리하고, 새로운 발행 후 관측을 확보해야 합니다.
- 다음 연구에서는 종목이 시장·업종에 비해 약해지는 정도를 분리하고, 날짜별 성적과 잘못된 매도 경고 비용을 함께 비교합니다.

재현: `python scripts/research_joint_indicator.py` · 검증: `python scripts/test_joint_indicator.py`
