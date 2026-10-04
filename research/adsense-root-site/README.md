# AdSense 등록 주소의 홈페이지

등록 주소 [bumblev95.github.io](https://bumblev95.github.io/)에 시장 홈페이지가 게시되었습니다. 기존 시장 사이트 `/S-P-500-/`도 계속 사용합니다. 이 폴더의 `index.html`은 게시된 루트 페이지의 사본이며, `base` 태그를 통해 기존 프로젝트의 CSS·JavaScript·시장 자료와 종목 페이지를 사용합니다. iframe이나 자동 이동 페이지가 아닙니다.

## 게시 확인 — 2026-10-04

- 공개 저장소: [bumblev95/bumblev95.github.io](https://github.com/bumblev95/bumblev95.github.io)
- Pages 게시 소스: `main` 브랜치, `/(root)` 폴더, HTTPS
- 게시 커밋: `7f2751fd7f704033daa164028f8c1bf5f2c7bdbc`
- [Pages 배포 실행 37190174241](https://github.com/bumblev95/bumblev95.github.io/actions/runs/37190174241): 성공
- 실제 루트 페이지에서 시장 뉴스·섹터 그래프·종목 링크와 계정 확인 태그 `ca-pub-9723666081819297`를 확인했습니다.

실제 광고는 **비활성화**되어 있습니다. 계정 확인 태그와 정상 게시를 확인한 것이며 Google의 소유권 확인이나 사이트 심사가 완료됐다는 뜻은 아닙니다.

## AdSense에서 이어서 진행

1. 사이트 소유권 확인 방법으로 **메타 태그**를 선택합니다.
2. 게시된 계정 ID를 확인하고 **코드를 삽입했습니다 → 확인**을 누릅니다.
3. 실제 운영할 호스팅 조건을 정리한 뒤 사이트 검토를 요청합니다.
4. 사이트 승인·실제 광고 단위 ID·개인정보 설정을 준비한 뒤 [광고 연결 안내](../AD-MONETIZATION.md)에 따라 광고를 활성화합니다. 계정이 요구하는 정확한 `ads.txt` 내용은 새 루트 저장소의 최상위에 넣어야 합니다.

루트 페이지는 기존 프로젝트의 공개 자산에 의존합니다. 시장 자료와 CSS·JavaScript는 원래 프로젝트에서 갱신됩니다. 메인 `index.html`의 구조나 네비게이션이 바뀌면 이 사본과 루트 저장소의 `index.html`도 함께 갱신해야 합니다. 루트 HTML은 기존 메인 HTML의 `<head>` 바로 뒤에 `<base href="https://bumblev95.github.io/S-P-500-/">`를 추가한 것입니다.

광고 계정 연결이나 Google의 사이트 승인은 GitHub Pages의 상업 이용을 허가하는 절차가 아닙니다. 실제 광고를 켜기 전에는 [호스팅·광고 연결 안내](../AD-MONETIZATION.md)를 확인해야 합니다.

참고: [GitHub 사용자 사이트 만들기](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site), [AdSense 사이트 소유권 확인](https://support.google.com/adsense/answer/7584263)
