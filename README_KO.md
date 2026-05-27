# S&P 500 섹터 밸류에이션 대시보드 v10 가족용 심플 패키지

이 패키지는 GitHub Pages에 바로 올려서 테스트할 수 있는 가족용 심플 버전입니다.

브라우저에서 Yahoo/FMP를 직접 호출하지 않습니다. 대신 GitHub Actions가 데이터를 받아 CSV로 저장하고, 대시보드는 같은 저장소의 CSV만 읽습니다.

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

## 자동 업데이트되는 항목

### 가격

`Update S&P 500 EOD prices` workflow가 Yahoo Finance의 EOD 데이터를 받아 아래 파일을 갱신합니다.

```text
prices/latest_prices.csv
```

대시보드에서는 `현재 섹터 가격 불러오기` 버튼을 누르면 이 CSV에서 가격을 불러옵니다.

### 펀더멘털 / 추정치

`Update S&P 500 fundamentals` workflow가 yfinance/Yahoo Finance 데이터를 받아 아래 파일을 갱신합니다.

```text
fundamentals/latest_fundamentals.csv
```

대시보드에서는 `현재 섹터 펀더멘털 자동채우기` 버튼을 누르면 가능한 항목을 자동 입력합니다.

자동 입력 가능한 항목은 다음과 같습니다.

- Forward EPS
- EPS CAGR %, Yahoo의 earningsGrowth 기반
- 매출 성장률 %, Yahoo의 revenueGrowth 기반
- 매출총이익률 %
- 영업이익률 %
- Exit P/E, forward P/E를 시작점으로 사용
- 리스크 점수 일부 항목, beta / debtToEquity / margin / forward P/E 기반

자동 데이터는 투자 판단의 최종값이 아니라 시작점입니다. 중요한 회사는 직접 확인하고 표에서 수정하세요.

## GitHub에 올리는 방법

1. 이 ZIP 파일을 압축 해제합니다.
2. 안에 있는 모든 파일과 폴더를 GitHub 저장소의 root에 업로드합니다.
3. 특히 아래 폴더가 누락되면 자동 업데이트가 안 됩니다.

```text
.github/workflows/
scripts/
prices/
fundamentals/
```

4. GitHub 저장소에서 `Settings` → `Pages`로 이동합니다.
5. Source를 `Deploy from a branch`로 설정합니다.
6. Branch는 `main`, folder는 `/root`로 설정합니다.
7. 저장 후 GitHub Pages 주소가 생성될 때까지 기다립니다.

## 처음 테스트하는 방법

1. GitHub 저장소의 `Actions` 탭으로 이동합니다.
2. 왼쪽에서 `Update S&P 500 EOD prices`를 선택합니다.
3. `Run workflow`를 눌러 실행합니다.
4. 완료되면 `prices/latest_prices.csv`가 갱신됩니다.
5. 같은 방식으로 `Update S&P 500 fundamentals`도 실행합니다.
6. 완료되면 `fundamentals/latest_fundamentals.csv`가 갱신됩니다.
7. GitHub Pages 대시보드를 열고 URL 끝에 아래처럼 붙입니다.

```text
?v=10
```

8. 대시보드에서 아래 버튼을 누릅니다.

```text
현재 섹터 가격 불러오기
현재 섹터 펀더멘털 자동채우기
```

## 기본 기준값 설명

가족용 기본값은 아래처럼 설정했습니다.

- 투자 기간: 5년
- 기본 할인율: 10%
- Bear 성장률 조정: -5%p
- Bull 성장률 조정: +5%p
- 적정 범위 허용치: -10%

이 기준은 S&P 500 전체를 대략 비교하기에는 무난합니다. 다만 성장주, 경기민감주, 금융주, 에너지주는 업종 특성이 강하기 때문에 중요한 기업은 직접 조정하는 것이 좋습니다.

## 주의사항

- Yahoo/yfinance 데이터는 무료로 접근 가능한 데이터라서 가끔 빈칸이 생길 수 있습니다.
- Forward EPS와 성장률은 출처마다 다를 수 있습니다.
- 이 대시보드는 빠른 상대평가용 도구이며, 투자 조언이 아닙니다.
