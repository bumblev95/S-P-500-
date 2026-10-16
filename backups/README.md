# 수정 전 파일 백업

## 2026-10-15 · PR #56

- 원본 main commit: `53b13ee5f7394bbc88e9b597114f7c534edab88e`
- 압축 백업: [2026-10-15-pr56-prechange-53b13ee5.tar.gz](2026-10-15-pr56-prechange-53b13ee5.tar.gz)
- 압축 파일 검증: `sha256sum -c backups/2026-10-15-pr56-prechange-53b13ee5.tar.gz.sha256`
- 백업에는 이번 수정으로 바뀌는 기존 파일 원본과 체크섬, 신규 파일 목록, 복원 도구가 있습니다. 원본은 위 main commit에서 직접 추출했습니다. 비밀키나 자격증명은 포함하지 않습니다. 운영 데이터 전체를 되감는 백업이 아닙니다.

### 롤백 방법

1. 저장소 최상위에서 `mkdir -p /tmp/sp500-pr56-restore && tar -xzf backups/2026-10-15-pr56-prechange-53b13ee5.tar.gz -C /tmp/sp500-pr56-restore`를 실행합니다.
2. `python /tmp/sp500-pr56-restore/restore.py --repo .`로 백업 체크섬과 현재 파일을 검사합니다. 기본값은 확인만 수행합니다.
3. 표시된 변경을 확인한 뒤 같은 명령에 `--apply`를 추가하면 기존 파일을 복원하고 이번에 새로 만든 파일을 제거합니다. 수정 이후 다른 내용으로 바뀐 파일이 있으면 덮어쓰지 않고 중단합니다.
4. 복원 diff와 검사를 검토하고 별도 PR로 적용합니다. 백업 자체는 남습니다. 이후 갱신된 주가·뉴스·운영 모델·거래 기록은 복원 대상에 없습니다.

원하면 “PR #56 백업 기준으로 롤백해 줘”라고 요청할 수 있습니다.

## 2026-10-16 · 금융·국제 문맥 번역

- 원본 main commit: `42b8d5c4c836ff84fbd99376571e4b4f8f19f4c5`
- 읽을 수 있는 실제 원본 백업: [2026-10-16-context-prechange-42b8d5c](2026-10-16-context-prechange-42b8d5c/README.md)
- 검증: `(cd backups/2026-10-16-context-prechange-42b8d5c && sha256sum -c SHA256SUMS)`
- 기존 공개 파일 8개의 원본과 SHA-256, 적용 후 파일 해시, dry-run 기본 복원 도구를 포함합니다. 압축파일 대신 각 파일을 직접 열어 확인할 수 있습니다.

### 롤백 방법

1. 저장소 최상위에서 `python backups/2026-10-16-context-prechange-42b8d5c/restore.py --repo .`로 체크섬과 변경 후 파일을 검사합니다. 아직 파일을 바꾸지 않습니다.
2. 복원 대상과 diff를 검토한 뒤 `--apply`를 추가하면 이번 변경의 기존 코드·검사·workflow·검토 번역 파일만 원본으로 복원합니다. 이후 다른 작업으로 수정된 파일이 있으면 전체 적용을 중단합니다.
3. 별도 PR로 테스트 후 배포합니다. 신규 회귀 fixture, 백업, 수정 이력은 삭제하지 않고 남깁니다. 이후 갱신된 가격·뉴스 snapshot·연구/거래 기록은 복원 대상이 아닙니다. 복원 도구가 충돌을 보고하면 무리하게 강제 실행하지 말고 별도 병합으로 해결합니다.

## 2026-10-16 · 실제 수집에서 발견한 추가 두 사례

- [후속 수정 직전 원본](2026-10-16-context-followup-dd2256c/README.md)은 PR #59 병합 상태 `dd2256c88a2d53300b2c037737ca7e4f289f1a88`의 파일입니다. 기존 공개 파일 6개를 그대로 보존하고 코드·테스트·fixture·검토 번역 4개를 복원 대상으로 지정합니다.
- 확인: `(cd backups/2026-10-16-context-followup-dd2256c && sha256sum -c SHA256SUMS)`
- dry run: `python backups/2026-10-16-context-followup-dd2256c/restore.py --repo .`
- 검토 후 `--apply`를 추가하면 후속 변경만 복원합니다. 처음 변경 이전까지 되돌리려면 이 후속 백업을 먼저 복원하고 위의 `2026-10-16-context-prechange-42b8d5c` 백업을 이어서 복원합니다. 두 도구 모두 이후 수정이 있으면 전체 적용을 중단하며, 파일을 삭제하지 않습니다. 별도 PR로 검증 후 배포하세요.
