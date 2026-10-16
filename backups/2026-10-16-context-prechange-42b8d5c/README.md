# 문맥 번역 수정 전 백업

공개 저장소 main `42b8d5c4c836ff84fbd99376571e4b4f8f19f4c5`의 기존 파일 8개를 `original/`에 그대로 보관합니다. 비공개 캐시, 비밀키, 사용자 컴퓨터의 파일, 운영 모델·거래/연구 기록은 포함하지 않습니다.

- `manifest.json`: 수정 전과 수정 후 해시, 복원 범위
- `SHA256SUMS`: 보관 파일 무결성 검증
- `restore.py`: 확인만 하는 dry-run이 기본. 이후 수정과 충돌하면 전체 적용 전에 중단

저장소 최상위에서 `python backups/2026-10-16-context-prechange-42b8d5c/restore.py --repo .`를 실행해 확인합니다. 직접 복원을 결정했을 때만 `--apply`를 추가하고, 검증한 별도 PR로 배포하세요. 새 fixture와 백업·이력 파일, 운영 snapshot은 삭제하거나 되감지 않습니다.
