# SEC 실적 수집과 학습 연결

2026-09-12 공식 문서와 현재 코드를 재점검했습니다. 현재 서버의 403은 확인됐지만
원인이 연락처 누락인지, 서버 주소에 대한 접근 제한인지는 확정하지 못했습니다.

## 먼저 바로잡은 연결 설정

SEC는 요청자 정보를 선언한 User-Agent를 안내하며 예시에 조직명과 연락처 이메일을
포함합니다. 기존 코드에는 프로그램명과 저장소 주소만 있었습니다. 이제 SEC 요청은
실제 연락처를 담은 `SEC_USER_AGENT`가 설정된 경우에만 실행됩니다. 이 값은 SEC에만
보내며 코인 제공자에는 보내지 않습니다. 403/429가 발생하면 기존 대기 시간을 유지하고,
설정을 바꿨다는 이유로 차단 상태를 자동 해제하지 않습니다.

저장소 Settings → Secrets and variables → Actions → New repository secret:

- Name: `SEC_USER_AGENT`
- Secret: `JackForecast/1.0` 뒤에 공백과 실제 연락용 이메일

예시를 그대로 복사하지 말고 사용 가능한 실제 연락처로 설정합니다. 워크플로가 이
secret을 환경 변수로 전달하도록 연결했습니다. 아직 연락처를 등록하거나 자동
수집 성공을 확인한 것은 아닙니다. 연락처를 소스 코드나 공개 JSON에 저장할 필요는 없습니다.

공식 자료: [SEC 접근 정책](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data),
[GitHub Actions secrets 설정](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

## 확보 경로

| 경로 | 역할 | 현재 지원 상태 |
| --- | --- | --- |
| CompanyFacts API | 기업별 표준 재무 수치와 원래 공시일 수집 | 연결 준비, 연락처 설정 및 접근 성공 확인 필요 |
| 공식 `companyfacts.zip` 또는 개별 CompanyFacts JSON | 정상적으로 확보한 파일에서 원하는 기업만 가져오기 | 네트워크 없이 가져오는 스크립트 추가 |
| Financial Statement Data Sets | 분기별로 배포되는 공시 당시 숫자와 제출 정보로 장기 학습 자료 구성 | 형식 검토 완료, SUB/NUM 전용 변환기는 아직 미구현 |

CompanyFacts API는 별도 API 키가 필요하지 않습니다. 공식 일괄 ZIP은 매일 갱신됩니다.
API와 동일한 SEC 접근 정책이 적용되므로 ZIP 경로가 서버의 접근 제한을 해결한다고
가정하지 않습니다. 대규모 초기 수집에는 일괄 파일이 적합하지만 현재 15개 기업만
필요하다면 기업별 요청이 더 작습니다. 브라우저에서 SEC를 직접 호출하는 대신
서버에서 수집하고 사이트는 가공한 JSON을 읽도록 유지합니다.

공식 자료: [SEC API와 bulk 파일](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

Financial Statement Data Sets는 실제 데이터가 2009년 4월부터 시작하고, 2009 Q1은
헤더만 있는 파일입니다. SUB의 `adsh`로 NUM을 연결해 기업·공시일·접수 시각·태그·금액을
보존할 수 있습니다. 분기 ZIP의 분기는 공시를 제출한 분기이므로 회사의 실적 분기와
같다고 가정하면 안 됩니다. 단위, 연결 대상, 세그먼트와 `qtrs` 기간을 확인해야 합니다.
이 파일들은 현재의 CompanyFacts ZIP 가져오기 스크립트와 호환되지 않습니다.

공식 자료: [분기 데이터](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets),
[SUB/NUM 형식 설명](https://www.sec.gov/files/financial-statement-data-sets.pdf).

## 확보한 파일을 학습에 넣기

정상적으로 받은 공식 CompanyFacts 파일에 대해 저장소 루트에서 실행합니다.

```sh
python scripts/import_sec_companyfacts.py /absolute/path/to/CIK0001045810.json
# 또는 공식 CompanyFacts 일괄 파일에서 대표 15개 기업만 선택
python scripts/import_sec_companyfacts.py /absolute/path/to/companyfacts.zip
python scripts/build_environment_research.py --offline
python -m unittest discover -s scripts -p test_environment_research.py
```

첫 명령은 네트워크에 접속하지 않습니다. 기업 식별번호, 날짜, 사용 가능한 연간
USD 실적을 확인하고 `research/inputs.json`의 주식 부분을 갱신합니다. 입력 파일의
해시와 가져온 시각을 기록하며, 실제 다운로드 시각을 모르면 지어내지 않습니다.
잘못된 기업, 중복 기업, 기존보다 짧은 기간의 파일은 거절합니다. 실제 SEC 파일로
가져오기를 완료한 상태는 아니며, JSON/ZIP 형식·공시일·식별번호 테스트를 통과했습니다.
`--offline` 학습은 기존 가격 캐시도 있어야 실행할 수 있습니다.

현재 모델에는 연간 매출 성장률, 순이익률, 영업현금흐름/매출, 부채/자산을 연결합니다.
공시일 다음 날짜부터 사용하고, 나중에 나온 수정 공시를 앞선 예측에 넣지 않습니다.
실적 추가 모델과 기존 모델은 같은 날짜·같은 종목에서 비교합니다. 현재 시점의
재무제표를 과거 모든 날짜에 복사하거나, 없는 지표를 0으로 대체하지 않습니다.

## 다음에 추가할 실적 정보

현재 파서는 연간 지표만 사용합니다. 연결을 해결한 뒤에는 분기 매출·마진 변화와
실적 발표 후 경과일을 우선 추가하는 것이 적절합니다. 분기와 누적 실적을 구분하고,
같은 공시 시점에서 사용 가능한 기간을 맞춰야 합니다. EPS와 주당 지표는 주식 분할과
가중평균 주식 수를 확인하기 전까지 조정 주가와 그대로 결합하지 않습니다.
가이던스·시장 예상 대비 실적은 현재 CompanyFacts 파서에 없으므로 별도의 발표 자료와
당시 예상치가 필요합니다. 자료 수집 성공만으로 주가 예측 오차가 줄었다고 판단하지 않고,
가격만 사용한 기준 모델과 후반 시점 검증을 다시 수행합니다.
