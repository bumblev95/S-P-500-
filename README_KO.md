# S&P 500 가족용 주식 대시보드 v23

## 현재 페이지 구성

- `index.html`: 초보자용 주식 가이드 (사이트 홈)
- `beginner.html`: 기존 즐겨찾기를 홈으로 연결
- `advanced.html`: 기존 밸류에이션·섹터·관심종목 고급 대시보드
- `crypto.html`: 현물 가격·유통량·FDV·현물 추세 가이드
- `futures.html`: 완료된 5분봉·15분봉·일봉의 단기 선물 패턴과 롱·숏 조건

현물 일별 관측은 CoinGecko를 사용하며 선물 가격으로 대체하지 않습니다. 단기 선물 화면은 열린 동안 Hyperliquid 공개 API를 60초마다 조회합니다. 신호는 현재가·호가 90초 이내 및 완료 봉 연속성을 요구하며 연결 실패 시 관망합니다. 학습형 코인 AI 또는 수익성 검증을 마친 전략은 아닙니다.

아래는 이전 버전 기록입니다. 기존 고급 화면을 갱신할 때는 이제 `advanced.html`을 수정하세요.

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
