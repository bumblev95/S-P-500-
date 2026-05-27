# S&P 500 가족용 주식 대시보드 v19

v19은 아버지가 모바일에서 보기 쉽게 **오늘 볼 종목**, **아빠 관심종목 TOP**, **실적·위험 주의**를 먼저 보여주는 버전입니다.

## 주요 기능

- S&P 500 섹터별 보기
- 가족 Google Sheet 관심종목 연동
- 관심종목 TOP 10 카드
- 4개월 스윙 / 1년 단기 / 3년 중기 / 5년 기본 모드
- 가격, Forward EPS, 성장률, 마진 자동 적용
- 52주 위치, 실적 발표 경고, PEG, 성장률 갭, 상승여력 표시
- 모바일 보기 버튼

## GitHub에 올릴 때 덮어쓸 파일

아래 파일은 v19 파일로 덮어쓰는 것을 권장합니다.

```text
index.html
scripts/update_eod_prices.py
scripts/update_fundamentals.py
.github/workflows/update-eod-prices.yml
.github/workflows/update-fundamentals.yml
```

## 조심할 파일

이미 Google Sheet URL을 설정했다면 아래 파일은 덮어쓰지 않는 것이 좋습니다.

```text
config/watchlist_config.json
```

덮어썼다면 기존 `sheetCsvUrl`, `submitUrl`을 다시 넣으면 됩니다.

## Google Sheet 관심종목 저장이 안 될 때

1. `config/watchlist_config.json`의 `submitUrl`이 Apps Script Web App URL인지 확인합니다.
2. URL이 `/exec`로 끝나는지 확인합니다.
3. Apps Script 배포 설정이 아래와 같은지 확인합니다.

```text
Execute as: Me
Who has access: Anyone
```

4. Apps Script 코드 맨 위에 `@OnlyCurrentDoc`가 있는지 확인합니다.
5. 대시보드에서 관심종목을 추가한 뒤 Google Sheet의 `custom_tickers` 시트에 티커가 들어오는지 확인합니다.

## Google Sheet CSV URL

가족 관심종목을 GitHub Actions가 읽으려면 `sheetCsvUrl`도 필요합니다.

Google Sheet에서:

```text
파일 → 공유 → 웹에 게시 → custom_tickers 시트 → CSV
```

나온 URL을 `config/watchlist_config.json`의 `sheetCsvUrl`에 넣습니다.

## 업데이트 후 테스트

GitHub Pages 주소 끝에 붙여서 캐시를 피합니다.

```text
?v=18
```

그리고 GitHub Actions에서 수동 실행합니다.

```text
Update S&P 500 EOD prices
Update S&P 500 fundamentals
```


## v19 Google Sheet 저장 문제 해결

대시보드에서 관심종목이 Google Sheet에 안 들어가면 Apps Script 코드를 `google_apps_script_watchlist_v19.gs` 내용으로 교체하세요.

이 버전은 CORS 문제를 피하기 위해 `doGet`으로도 티커 저장을 처리합니다. 테스트 방법:

```text
https://script.google.com/macros/s/....../exec?symbol=SOFI&name=SoFi&sector=Watchlist&subIndustry=Fintech
```

이 URL을 브라우저에서 열었을 때 Google Sheet의 `custom_tickers` 시트에 SOFI가 들어오면 정상입니다.

중요: Apps Script를 수정한 뒤에는 반드시 `배포 → 배포 관리 → 새 버전`으로 다시 배포해야 합니다. URL은 `/exec`로 끝나는 Web App URL을 사용하세요.


## v20 관심종목 보안 설정

v20부터는 대시보드 화면에 Apps Script URL을 표시하지 않습니다. URL은 `config/watchlist_config.json`의 `submitUrl`에서만 읽습니다.

### 1. Apps Script PIN 설정

Google Sheet에서 `확장 프로그램 → Apps Script`를 열고, `google_apps_script_watchlist_v20.gs` 내용을 붙여넣습니다.

코드 상단에서 아래 부분을 가족 PIN으로 바꿉니다.

```javascript
const FAMILY_PIN = 'CHANGE_ME_TO_YOUR_FAMILY_PIN';
```

예:

```javascript
const FAMILY_PIN = '1234';
```

PIN은 너무 간단하게 하지 않는 것이 좋습니다.

### 2. 새 버전으로 배포

Apps Script에서:

```text
배포 → 배포 관리 → 연필 아이콘 → 버전: 새 버전 → 배포
```

Web App URL은 반드시 `/exec`로 끝나는 주소를 사용합니다.

### 3. 테스트

브라우저에서 다음처럼 열어봅니다.

```text
https://script.google.com/macros/s/너의_ID/exec?symbol=SOFI&pin=너의_PIN
```

정상이라면:

```json
{"ok":true,"symbol":"SOFI"}
```

그리고 Google Sheet의 `custom_tickers` 탭에 SOFI가 들어가야 합니다.

### 4. 대시보드 사용

대시보드에서 `관심종목 추가`를 누르고 가족 PIN을 입력합니다. PIN은 해당 브라우저에만 저장되며 GitHub HTML에는 저장되지 않습니다.

