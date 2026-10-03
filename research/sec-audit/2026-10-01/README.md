# SEC annual coverage: 2026-10-01

기준은 `35a3316fe23c7306d9114bcc60f04a116814842c`다. 직전
`6c537be0d4615aefff7706f034b8410569c217dc`와 constituent 목록·sourceHash는
같고 retrievedAt만 달라졌다. universe 변경이 아니라 annual revenue 선택과
새 registrant의 이력 문제를 조사했다.

| 구분 | 기준 checkpoint | 고정 원문을 사용한 offline replay |
|---|---:|---:|
| 대상 issuer / ticker | 500 / 503 | 500 / 503 |
| 사용 가능 issuer / ticker | 488 / 491 | 497 / 500 |
| fallback issuer | 0 | 9 |
| 결측 ticker | 12 | APA, HONA, SYF |

이 결과는 parser/coverage 검증이다. production `inputs.json`, 모델, 예측,
paper 계좌·원장·pinned momentum-boost는 변경하지 않았다. 다른 491개 ticker의
기존 history는 offline replay에서도 그대로 보존했다.

## 12개 원인과 처리

| Ticker | CIK | 확인된 원인 | 처리 |
|---|---:|---|---|
| FITB | 35527 | 표준 annual net-interest / noninterest 수익이 분리되어 있음 | 동일 filing·기간의 두 표준 항목만 합산 |
| SJM | 91419 | 표준 `RevenueFromContractWithCustomerIncludingAssessedTax` 누락 | 이 CIK에 한정한 태그 fallback |
| TFC | 92230 | 표준 annual net-interest / noninterest 수익이 분리되어 있음 | 동일 filing·기간의 두 표준 항목만 합산 |
| ODFL | 878927 | 표준 including-tax 매출 태그 누락 | 이 CIK에 한정한 태그 fallback |
| VLO | 1035002 | 표준 including-tax 매출 태그 누락 | 이 CIK에 한정한 태그 fallback |
| RF | 1281761 | 표준 annual net-interest / noninterest 수익이 분리되어 있음 | 동일 filing·기간의 두 표준 항목만 합산 |
| CRWD | 1535527 | 표준 including-tax 매출 태그 누락 | 이 CIK에 한정한 태그 fallback |
| SYF | 1601712 | net revenue에는 custom retailer-share 조정이 필요 | 결측 유지; 다른 은행 합산식을 적용하지 않음 |
| KHC | 1637459 | 표준 including-tax 매출 태그 누락 | 이 CIK에 한정한 태그 fallback |
| APA | 1841666 | revenue 공시는 존재하지만 custom / dimensioned 문맥이며 CompanyFacts에 사용 가능한 표준 annual revenue가 없음 | 결측 유지; pro-forma 매출·Apache 과거 CIK를 대체하지 않음 |
| HONA | 2089271 | 현재 CompanyFacts 매출은 분기·반기뿐; 아직 annual 매출 이력이 없음 | 결측 유지; Honeywell parent 실적·반기 연환산을 사용하지 않음 |
| XOM | 2115436 | 2026-07-01 새 successor registrant는 분기 이력뿐 | 공시로 확인된 기존 CIK 34088의 전환 전 annual facts만 연결 |

`no_standard_annual_facts`는 기존 parser가 snapshot을 만들지 못했다는 뜻이다.
모든 표준 annual USD 재무항목이 실제로 없다는 뜻은 아니다. revenue가 없어도
순이익·현금흐름·자산 등은 존재할 수 있다. HONA도 registration filing에는
과거 audited combined statements가 있지만, 이 수집기의 annual CompanyFacts
경로에서 사용할 수 있다는 뜻은 아니다.

은행 분모는 `InterestIncomeExpenseNet + NoninterestIncome`으로 명시했다.
2025년 확인 값은 FITB 9,017, TFC 20,319, RF 7,526 million USD다.
두 항목의 start·end·filed·accession·form이 모두 같아야 하며 중복 문맥의
값이 충돌하면 합산하지 않는다. gross interest, 일부 customer revenue,
tax-equivalent 조정, credit provision 이후 금액으로 바꾸지 않는다.
이 분모는 일반기업의 매출이나 은행의 비GAAP/FTE headline revenue와 의미가
다를 수 있으므로 `revenueBasis`와 실제 두 항목 evidence를 남긴다.

## 공시일과 provenance

- annual 기간 330–400일, USD, 기존 10-K/10-Q와 amendment 허용 범위를 유지한다.
- growth는 같은 태그·같은 source CIK의 비교 가능한 annual 기간만 사용한다.
  margin은 동일 start/end, balance ratio는 동일 end를 요구한다.
- snapshot의 다음 날짜부터 사용할 수 있고 period end의 550일 제한을 유지한다.
  뒤늦은 정정공시는 이전 날짜의 feature에 들어가지 않는다.
- XOM의 mapping은 [8-K12B](https://www.sec.gov/Archives/edgar/data/2115436/000119312526291990/d71068d8k12b.htm)로
  확인했다. mapping 공시일인 2026-07-01 전에는 successor series에 이전 CIK의
  수치를 넣지 않는다. source CIK·원 공시일·accession을 남기고, 전환 이후
  old registrant의 공시도 섞지 않는다. 새 CIK가 직접 annual facts를 제공하면
  해당 기간의 기존 standard 선택이 우선한다.
- 현재 snapshot을 과거 날짜로 복사하거나 quarterly/YTD 값을 연환산하지 않는다.
  실제 원문의 각각의 공시일로 history를 복원한다. current CompanyFacts는
  certified vintage feed가 아니며 API의 과거 수치·taxonomy 자체가 바뀔 수 있다.

일반 태그 목록 `TAGS`는 바꾸지 않았다. 이를 import하는 고정 quarterly 실험의
선택 범위가 이번 annual fallback 때문에 조용히 달라지지 않는다.

## 재현과 수집

```sh
python scripts/audit_sec_coverage.py --check
python -m unittest discover -s scripts -p test_sec_coverage.py
python -m unittest discover -s scripts -p test_research_inputs.py
python -m unittest discover -s scripts -p test_sec_import.py
python -m unittest discover -s scripts -p test_sp500_research.py
```

[manifest.json](manifest.json)은 baseline checkpoint·원문 URL·취득 시각과
raw SHA256, 압축 SHA256을 고정한다. `sources/`에는 수정하지 않은 공식
CompanyFacts 13개, 공시 statement 5개, submissions 4개와 기존 checkpoint·parser,
NVDA 대조 원문을 gzip으로 보존했다. shallow checkout에서도 네트워크 없이
재현할 수 있다. [report.json](report.json)은 각 원인, 태그별 annual 건수,
fallback, source CIK, evidence, code/policy hash를 기록한다. 원문·코드가 바뀌면
`--check`가 실패하므로 검토 후에만 report를 다시 생성한다.

기준 commit은 raw CompanyFacts hash를 공개하지 않았다. 이번 공식 원문은
2026-10-01에 새로 확보한 것으로, 기준 commit 당시의 정확한 raw vintage라고
주장하지 않는다. 원래 coverage와 universe는 기준 checkpoint bytes로 검증했다.

정상 수집은 기존 `SEC_USER_AGENT` 설정·20시간 재사용·issuer별 중복 제거·
25개 단위 checkpoint·접근 제한 시 24시간 backoff를 유지한다. reviewed XOM
predecessor만 추가 요청을 허용하며 401/403/429가 발생하면 그 요청부터 이후
모든 SEC 요청을 중단한다. parser/policy가 바뀌면 fresh cache도 재처리할 수
있고, offline/backoff 중에는 원문 cache만 처리한다. 원문이 없으면
`raw_source_unavailable`로 기록한다. 실패·빈 refresh가 기존 유효 history를
지우지 않으며 imported source를 새 API 조회로 표시하지 않는다.

운영 결과는 `inputs.json.secCoverage.diagnostics`에 parser/policy version,
원인·fallback 상태·canonical payload hash·처리 시각을 남긴다. 개별 stock에는
source payload hash와 parser/policy version, fallback snapshot에는 원 항목 값·
태그·기간·공시일·CIK를 남긴다. JSON/ZIP import도 같은 parser와 coverage 계산을
사용한다. predecessor import는 실제 current CompanyFacts도 요구하며 전체
입력 검증·future filing 검사·기존 history 축소 방지를 통과한 뒤에 저장한다.

범위를 넘는 custom / dimensioned filing-level 수집은 별도 검토가 필요하다.
이번 coverage 확대는 예측력 개선이나 paper/live 승격의 근거가 아니다.
