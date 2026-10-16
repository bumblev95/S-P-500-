# 추가 문맥 보완 전 백업

[PR #59](https://github.com/bumblev95/S-P-500-/pull/59) 병합 commit `dd2256c88a2d53300b2c037737ca7e4f289f1a88`의 기존 공개 파일 6개입니다. 비밀키·비공개 캐시·운영 snapshot은 없습니다.

저장소 최상위에서 `python backups/2026-10-16-context-followup-dd2256c/restore.py --repo .`로 dry run을 확인합니다. 검토 후 `--apply`를 추가해 이번 두 사례의 보완만 복원할 수 있습니다. 처음 상태까지 복원하려면 이 백업 다음에 `2026-10-16-context-prechange-42b8d5c`를 복원하세요.

도구는 체크섬과 적용 후 해시를 확인해 이후 다른 수정이 있으면 쓰기 전에 중단합니다. 이력·백업·운영데이터를 삭제하지 않습니다. 별도 PR로 검사 후 배포하세요.
