# S&P 500 가족용 주식 대시보드 v23

## 현재 페이지 구성

- `index.html`: 초보자용 주식 가이드 (사이트 홈)
- `beginner.html`: 기존 즐겨찾기를 홈으로 연결
- `advanced.html`: 자동 데이터 기반 고급 리서치 워크스페이스
- `advanced-legacy.html`: 이전 수동 편집·가족 관심종목 관리 화면 (기존 저장값 유지)
- `crypto.html`: 현물 가격·유통량·FDV·현물 추세 가이드
- `futures.html`: 완료된 5분봉·15분봉·일봉의 단기 선물 패턴과 롱·숏 조건

현물 일별 관측은 CoinGecko를 사용하며 선물 가격으로 대체하지 않습니다. 단기 선물 화면은 열린 동안 Hyperliquid 공개 API를 60초마다 조회합니다. 신호는 현재가·호가 90초 이내 및 완료 봉 연속성을 요구하며 연결 실패 시 관망합니다. 학습형 코인 AI 또는 수익성 검증을 마친 전략은 아닙니다.

## 고급 분석 워크스페이스

화면을 열 때와 활성 화면에서 15분마다 가격·기업 지표·신용시장 파일을 읽습니다. 가격 수집은 기존 평일 장 마감 후 일정, 기업 지표는 매주 토요일 일정이며 실시간 가격이 아닙니다. 기업 지표 수집 후에도 Pages 갱신을 요청합니다.

- 섹터 흐름, 검색·수치 필터·정렬·관심종목 및 필터 결과 CSV 다운로드
- 최대 4종목의 공통 날짜 상대 가격, 연환산 변동성·최대 낙폭, 일별 로그 수익률 상관관계
- Forward EPS·이후 CAGR·Exit P/E·할인율·기간을 조정하는 시나리오와 민감도 표, 현재가가 요구하는 성장률
- 단기 진입 타이밍과 126·252거래일(약 6개월·1년) AI 채택 여부, 방향 기준선·하락 포착·외부표본 MAE 및 발행 후 평가 건수
- EPS 성장 둔화와 Exit P/E 정상화를 명시한 3년 Bear/Base/Bull 가치 시나리오(방향 예측이나 확률 아님)

누락 EPS는 대체하지 않습니다. P/E는 최신 가격 / 양수 Forward EPS, D/E는 원본 백분율 / 100입니다. 과거 매출 성장률은 미래 EPS CAGR으로 사용하지 않습니다. 섹터 P/E 중앙값은 해당 종목을 제외하고 갱신 범위 내 양수 P/E가 500 미만인 최소 5개 표본으로 구합니다. 섹터는 세부 사업모델까지 일치하는 비교군이 아닙니다.

EPS 배수 모형의 현재 가치는 `Forward EPS × (1+g)^(years−1) × Exit P/E / (1+d)^years`입니다. Forward EPS를 1년차 기준으로 가정합니다. 기본 성장률 0%, 할인율 10%, 3년은 편집 가능한 예시이며 추정 정확도를 보장하는 최적값이 아닙니다. 사용자 가정과 관심종목은 새 브라우저 저장 공간에만 보관하며 기존 가족 관리 정보는 읽거나 이전하지 않습니다.

비교는 배당 재투자·수수료를 제외한 가격 수익률입니다. 상관계수는 동일 시작·종료 날짜의 최소 20쌍이 필요합니다. 선택 종목들의 거래일 중 가격 누락이 있으면 일별 연환산 변동성을 표시하지 않습니다. 공개 이력은 다음 가격 수집부터 최대 253개로 확장됩니다. 그 전이나 신규 상장 등으로 자료가 짧으면 실제 관측 수·날짜와 기간 부족을 표시합니다.

AI 검증 화면은 기존 학습 결과를 읽고 현재 CSV와 가격·날짜가 맞는지 확인합니다. 채택 기준 미통과 AI는 보류합니다. MAE는 수익률 오차(%p)이며 가격 MAPE·투자 손실률과 구분합니다. 실제 발행 후 기록은 기존 추세 모형 기록이며 AI 실전 수익률이 아닙니다.

검증: `node scripts/test_advanced.cjs`, `python -m unittest discover -s tests -p test_forecasts.py`. 고급 분석 변경은 별도 GitHub Actions에서 검증합니다.

아래는 이전 버전 기록입니다. 이전 수동 화면은 이제 `advanced-legacy.html`에서 확인하세요.

v23은 상단 화면을 단순하게 유지하고, 종목을 클릭했을 때 매수가/목표가/손절가/유동성/추세/변동성 같은 세부 정보를 보여주는 버전입니다.

## 업데이트 시 덮어쓸 파일

```text
index.html
scripts/update_eod_prices.py
scripts/update_fundamentals.py
.github/workflows/update-eod-prices.yml
.github/workflows/update-fundamentals.yml
```

`config/watchlist_config.json`에는 Google Sheet URL이 들어가므로 기존 설정을 유지하세요.

## 새 데이터 컬럼

`prices/latest_prices.csv`에는 52주 위치, 이동평균, 4개월 변동성/최대하락폭 등이 포함됩니다. GitHub Actions의 가격 workflow를 다시 실행해야 반영됩니다.


## v24 업데이트
- 섹터 히트맵을 다시 표시합니다.
- 섹터 히트맵은 섹터별 평균 단기점수와 고평가 비중을 보여주며, 클릭하면 해당 섹터로 이동합니다.


## v25 관심종목 동기화 수정

- Google Sheet/custom_tickers에서 불러온 티커는 항상 `Watchlist` 섹터로 들어갑니다.
- `공유 관심종목 동기화` 버튼을 누르면 Google Sheet에서 삭제한 관심종목이 브라우저 localStorage에서도 제거됩니다.
- 관심종목을 새로 추가한 뒤 가격/EPS가 바로 보이지 않는 것은 정상입니다. GitHub Actions의 `Update S&P 500 EOD prices`와 `Update S&P 500 fundamentals`를 다시 실행해야 `prices/latest_prices.csv`와 `fundamentals/latest_fundamentals.csv`에 반영됩니다.
- 화면이 계속 예전 데이터를 보이면 URL 끝에 `?v=25`를 붙여서 열고 `공유 관심종목 동기화`를 누르세요.
