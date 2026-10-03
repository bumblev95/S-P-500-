# 화면 상태 표시

`assets/market-visuals.js`와 `assets/status-indicators.css`가 홈·고급 분석·코인 현물·단기 선물에서 같은 상태 표시를 제공합니다. 데이터 수집, 모델 채택, 점수, 매매 조건은 바꾸지 않습니다.

| 표시 | 원래 값 | 화면 표현 |
| --- | --- | --- |
| 종합 시장 위험 | `DecisionSupport.risk().status` | `stable` 원활 / `watch` 주의 / `risk` 경보 |
| 신규 진입 | 기존 `plan.code` | `avoid` 진입 보류 / `watch`, `pullback`, `confirm` 관망 / `buy` 진입 검토 |
| 단기 추세 | 기존 공통 추세 점수 | 실제 0–100 값과 기존 35·46·60·78 경계 |
| 코인 현물 | 기존 `spotAction` | 신규 매수 대기 / 관망·눌림목 대기 / 분할매수 검토 |
| 단기 선물 | 기존 `analysis.action` | 숏 검토 / 관망 / 롱 검토 |
| 과거 평가 시점 | 기존 `validation.dates` | 6개 미만 / 6–19개 / 20개 이상; 모두 정보색 |

상태 게이지의 바늘은 해당 단계의 중앙을 가리킵니다. 확률·수익률·투자 비중을 새로 계산하지 않습니다. 단기 추세만 원래 숫자를 바늘 위치로 사용합니다. 진입 보류는 신규 진입 조건이며 보유 주식의 매도 지시가 아닙니다.

자료 부족·알 수 없는 상태는 회색이며 바늘과 활성 단계가 없습니다. 선물 갱신 실패나 90초 경과도 바늘을 숨깁니다. 원래 신선도·완료 봉·AI 검증 조건은 그대로 적용됩니다. 위험 근거 표는 마지막 확보값과 관측일을 남겨 두고, 허용 기간이 지난 값은 회색 `판단 제외`로 표시합니다. 참고값·누락값도 위험 판단에 사용한 값과 구분합니다. 세부 기준·수집 상태·원자료는 각 행을 펼쳐 확인할 수 있습니다.

색상 외에도 상태명, 활성 단계, SVG의 접근성 설명을 제공합니다. 가격 기준과 기술 지표는 행 제목이 있는 요약 표로 읽을 수 있습니다.

검증:

```sh
node scripts/test_status_indicators.cjs
node scripts/test_stock_assessment.cjs
node scripts/test_crypto_page.cjs
node scripts/test_perp.cjs
```

`scripts/test_status_indicators_browser.cjs`는 실제 Chromium으로 320·390·1280px 화면, 펼친 위험 근거 표, 기간 전환, 가격·거래소 자료 실패를 확인하고 스크린샷을 남깁니다. 시계는 저장된 시장 자료의 수집 시각으로 고정하며, 거래소 응답은 테스트 내부 fixture만 사용합니다. 수집 파일을 수정하지 않습니다. Playwright가 설치된 환경에서 다음과 같이 실행할 수 있습니다.

```sh
node scripts/test_status_indicators_browser.cjs
```

별도 설치 경로는 `PLAYWRIGHT_MODULE`, 기존 Chromium 실행 파일은 `BROWSER_BIN`, 스크린샷 폴더는 `INDICATOR_SCREENSHOTS`로 지정할 수 있습니다. `.github/workflows/validate-status-indicators.yml`이 관련 파일 변경 시 단위 테스트와 브라우저 검증을 실행합니다.
