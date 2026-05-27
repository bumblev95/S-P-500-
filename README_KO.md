# S&P 500 + 가족 관심종목 대시보드 v15

이 버전은 가족용으로 UI를 단순화하고, 아버지처럼 중단기/스윙 투자 성향이 있는 사용자를 위해 추천 후보를 더 잘 보이도록 정리한 버전입니다.

## 주요 기능

- 가격 데이터: GitHub Actions가 Yahoo/yfinance EOD 데이터를 받아 `prices/latest_prices.csv`에 저장
- 펀더멘털 데이터: GitHub Actions가 Yahoo/yfinance 펀더멘털을 받아 `fundamentals/latest_fundamentals.csv`에 저장
- 투자 스타일: 4개월 스윙, 1년 단기, 3년 중기, 5년 기본
- 오늘 확인할 후보: 현재 섹터/검색 조건 기준 추천 후보 3개를 카드로 표시
- 섹터 히트맵: 섹터별 평균 추천점수를 시각화
- 추천 점수: 상대가치, PEG, 성장률 갭, 모멘텀, 리스크, 데이터 신뢰도를 조합
- 관심종목 추가: S&P 500 밖의 작은 주식도 추가 가능
- Google Sheet Watchlist 연동: 가족 공유 관심종목을 Google Sheet에 저장 가능

## GitHub에 올려야 하는 구조

ZIP 안의 내용물을 저장소 첫 화면(root)에 올리세요.

```text
index.html
README_KO.md
custom_tickers.csv
config/watchlist_config.json
prices/latest_prices.csv
fundamentals/latest_fundamentals.csv
scripts/update_eod_prices.py
scripts/update_fundamentals.py
.github/workflows/update-eod-prices.yml
.github/workflows/update-fundamentals.yml
google_apps_script_watchlist.gs
```

## 처음 테스트 순서

1. GitHub 저장소에 파일 업로드
2. `Settings → Actions → General → Workflow permissions`에서 `Read and write permissions` 선택
3. `Actions → Update S&P 500 EOD prices → Run workflow`
4. `Actions → Update S&P 500 fundamentals → Run workflow`
5. GitHub Pages 주소를 `?v=15`로 열기
6. 대시보드에서 `가격 불러오기`, `펀더멘털 자동 적용` 클릭

## Google Sheet 관심종목 연동

Google Sheet의 첫 시트 이름을 아래처럼 만드세요.

```text
custom_tickers
```

첫 행 헤더는 아래와 같이 입력하세요.

```text
symbol,name,sector,subIndustry,addedAt,source
```

Google Sheet에서:

```text
확장 프로그램 → Apps Script
```

`google_apps_script_watchlist.gs` 내용을 붙여넣고 저장합니다. 이 파일에는 `@OnlyCurrentDoc`가 포함되어 현재 Google Sheet만 접근하도록 권한을 제한합니다.

배포 설정:

```text
배포 → 새 배포 → 웹 앱
실행 사용자: 나
액세스 권한: 모든 사용자
```

배포 후 나온 Web App URL을 GitHub의 아래 파일에 넣으세요.

```text
config/watchlist_config.json
```

예시:

```json
{
  "sheetCsvUrl": "여기에 Google Sheet published CSV URL",
  "submitUrl": "여기에 Apps Script Web App URL",
  "notes": "family watchlist"
}
```

## 투자 스타일 해석

- 4개월 스윙: 모멘텀, 리스크, 상대가치를 더 크게 봄
- 1년 단기: 단기 회복 가능성, 상대가치, 성장률 갭을 균형 있게 봄
- 3년 중기: 성장률 갭과 적정가를 더 크게 봄
- 5년 기본: 장기 적정가와 필요 EPS 성장률을 중심으로 봄

## 주의

이 대시보드는 투자 추천을 확정하는 도구가 아니라 스크리닝 도구입니다. 특히 작은 주식은 변동성, 유동성, 재무 리스크가 크기 때문에 추천 점수가 높아도 추가 확인이 필요합니다.
