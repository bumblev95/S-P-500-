# S&P 500 섹터 밸류에이션 대시보드 v11 가족용 자동 펀더멘털 버전

이 패키지는 GitHub Pages에서 바로 테스트할 수 있는 S&P 500 섹터 밸류에이션 대시보드입니다.

## v11 변경점

- API 키 입력칸 등 가족용으로 불필요한 기능을 숨겼습니다.
- `현재 섹터 펀더멘털 자동 적용` 버튼을 누르면 Yahoo/yfinance에서 받아온 값이 있으면 기존 섹터 기본값을 덮어씁니다.
- Forward EPS, 매출 성장률, EPS 성장률, 매출 이익률, 영업이익률, Exit P/E를 자동 적용합니다.
- 할인율은 투자자 요구수익률이므로 자동 산정하지 않고 기본 10%를 사용합니다.
- 데이터가 없는 종목은 기존 섹터 기본값을 유지합니다.

## 포함 파일

```text
index.html
scripts/update_eod_prices.py
scripts/update_fundamentals.py
.github/workflows/update-eod-prices.yml
.github/workflows/update-fundamentals.yml
prices/latest_prices.csv
fundamentals/latest_fundamentals.csv
README_KO.md
```

## 설치 방법

ZIP 안의 내용물을 GitHub 저장소 root에 업로드하세요. ZIP 파일 자체를 업로드하는 것이 아니라, ZIP 안의 파일과 폴더를 그대로 올려야 합니다.

정상 구조는 아래와 같습니다.

```text
index.html
README_KO.md
prices/latest_prices.csv
fundamentals/latest_fundamentals.csv
scripts/update_eod_prices.py
scripts/update_fundamentals.py
.github/workflows/update-eod-prices.yml
.github/workflows/update-fundamentals.yml
```

## GitHub Actions 실행

처음 테스트할 때는 아래 두 workflow를 수동 실행하세요.

```text
Actions → Update S&P 500 EOD prices → Run workflow
Actions → Update S&P 500 fundamentals → Run workflow
```

이후에는 가격은 월~금 자동 업데이트, 펀더멘털은 주 1회 자동 업데이트됩니다.

## 대시보드 사용

GitHub Pages 주소 끝에 아래를 붙여서 캐시를 피하세요.

```text
?v=11
```

대시보드에서 아래 버튼을 누릅니다.

```text
현재 섹터 가격 불러오기
현재 섹터 펀더멘털 자동 적용
```

## 주의

Yahoo/yfinance 데이터는 무료로 접근 가능한 데이터라 일부 종목의 Forward EPS, 성장률, 마진 값이 비어 있을 수 있습니다. 그런 경우 대시보드는 기존 섹터 기본값을 유지합니다.
