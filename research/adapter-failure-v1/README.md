# 126일 보정 실패 진단 · adapter-failure-v1

`2026-10-12` 상태 업데이트의 126일 biasCorrected 실패를 같은 최종 검증 표본에서 재현하고, 가격 예측을 유지하는 방향 분류기와 가격 결합 방식을 비교한다. **검증된 투자 성과가 아닌, PIT 미완성 자료의 격리된 과거 진단**이다. 후보 선택·승격·실전 매매·TOP3·홈페이지 변경은 모두 비활성화한다.

자세한 한국어 분석은 [FINDINGS.md](FINDINGS.md), 모든 하위집단과 후보의 수치는 [output/metrics.csv](output/metrics.csv), 기계 판독 결과는 [output/results.json](output/results.json)에 있다. 원본별 SHA256와 커밋은 [input-manifest.json](input-manifest.json)에 기록한다.

## 재현

저장소 루트에서 Python 3.11 이상으로 실행한다. 계산에는 네트워크나 새 가격 다운로드가 필요 없다. 모델 입력과 PR #25에서 재사용한 함수의 원본을 모두 이 폴더에 고정했다.

```bash
python -m pip install -r research/adapter-failure-v1/requirements.txt
python research/adapter-failure-v1/run.py
python -m unittest discover -s research/adapter-failure-v1 -p test_run.py -v
python research/adapter-failure-v1/run.py --output research/adapter-failure-v1/replay
python research/adapter-failure-v1/verify_replay.py
```

`verify_replay.py`는 결과 JSON, 행별 예측 gzip, 전체 비교 CSV를 바이트 단위로 비교한다. Python/NumPy/scikit-learn 버전은 results.json에 보관하며 고정된 환경에서 재현한다. 원래 평가 파일의 저장된 소수점과 재계산의 미세한 차이는 최대 절대오차 1e-14를 허용하며, 통과 여부와 선택 결과는 일치해야 한다. 외부 폴더나 실전 경로에 출력하려 하면 실패한다.

`run.py`는 PR #25의 `label`, `date_weights`, `split_matured`, `ordered_probability`를 바이트가 동일한 복사본에서 직접 가져온다. 기존 adapter의 normalize/matured/fit/predict/compare/quantile/regime 함수도 그대로 사용한다. 복사본의 build/main 실행기는 호출하지 않는다. PR #25의 공동 분포·conditional/blend 연구를 새 결과로 재발표하거나, PIT 자료를 다시 수집하지 않는다.

## 기록과 한계

- 원본 main: `9e07f96df6b43689bb75dcc005329964db33e882`; 연구 run head: `06386c1f1fff501b136ece306346c5e37b2a7236`.
- PR #25 재사용 head: `1aa16f7a831b0aeed411593fe64464af94115cd5`. 이전 연구/검증 파일에는 쓰지 않는다.
- 126일 source validation은 2026-10-09에 생성됐고 마지막 target은 2026-10-08이다. 10월 12일 status 시각은 새로운 독립 검증 성과가 생긴 시각을 의미하지 않는다.
- 126일 최종 평가: 2024-10-03, 2025-04-07, 2025-10-07, 2026-04-09, 총 1,996행. 최초 모델의 앞부분 5,919행과 비교하지 않는다.
- 252일은 원본의 자료 부족 판정을 유지한다. 126일 성과를 252일 검증 완료로 확장하지 않는다.
- 기존 과거 결과를 확인한 뒤 만든 실험이다. 설정은 신규 후보 실행 전에 고정했지만, 과거 결과가 이미 알려져 있어 사전 미열람 검증으로 인정하지 않는다.
- PR #25의 historical readiness는 0/34이며, 새 표본 시점에도 완전한 구성종목·identity·가격 vintage·상장폐지/합병 lifecycle 증명이 없다. 새 시점의 PIT ready는 0으로 기록한다. 격리 자료로 재학습한 분류기는 구조 진단에만 사용한다.
- SPY의 당시 종가 이전 구간만 사용하지만, 저장된 현행 시계열은 당시 발표 vintage를 보증하지 않는다. 따라서 거시상황 구분도 격리 진단이다.
- 행별 분류가 하락이어도 매도 신호로 전달하지 않는다. 분류기 결과와 숫자 가격 전망은 별도 연구 필드에만 보존한다. 매매 비용·회전율·실제 수익은 이 실험에서 계산하지 않는다.
