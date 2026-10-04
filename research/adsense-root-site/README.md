# AdSense 등록 주소의 홈페이지 준비

현재 등록 주소는 `bumblev95.github.io`이며 기존 시장 사이트는 `/S-P-500-/`에 있습니다. 이 폴더의 `index.html`은 기존 메인 화면과 같은 내용을 표시하며, `base` 태그를 통해 기존 프로젝트의 CSS·JavaScript·시장 자료와 종목 페이지를 사용합니다. iframe이나 자동 이동 페이지가 아닙니다.

소유자의 계정 확인용 메타 태그는 들어 있지만 **아직 루트 주소에 게시되지 않았습니다**. 실제 광고도 비활성화 상태입니다.

## 루트 주소 게시

1. GitHub에서 소유자 `bumblev95`, 이름 **`bumblev95.github.io`**인 공개 저장소를 만들고 **Add README**를 켭니다. 이 이름은 사용자 루트 사이트에 필요한 이름입니다. 현재 연결 도구는 새 저장소 생성과 Pages 설정을 지원하지 않으므로 이 설정은 계정 소유자가 직접 하거나 승인된 브라우저 작업으로 진행해야 합니다.
2. 이 폴더의 `index.html`을 새 저장소 `main`의 최상위에 넣고 빈 `.nojekyll` 파일도 함께 넣습니다. 새 저장소가 만들어지면 파일 반영은 연결 도구로 진행할 수 있습니다.
3. 새 저장소의 **Settings → Pages → Build and deployment**에서 **Deploy from a branch → main → /(root) → Save**를 선택합니다.
4. 게시 완료 후 `https://bumblev95.github.io/`에서 시장 메인 화면이 정상적으로 열리는지 확인합니다. 메타 태그는 사이트의 HTML head에 있어야 합니다.
5. AdSense의 사이트 소유권 확인에서 **메타 태그**를 선택하고, 게시와 계정 ID를 확인한 뒤 **코드를 삽입했습니다 → 확인**을 누릅니다. 실제 운영할 호스팅 조건을 정리한 뒤 사이트 검토를 요청합니다.

루트 페이지는 기존 프로젝트의 공개 자산에 의존합니다. 시장 자료와 CSS·JavaScript는 원래 프로젝트에서 갱신됩니다. 메인 `index.html`의 구조나 네비게이션이 바뀌면 이 준비 파일과 새 루트 저장소의 `index.html`도 함께 갱신해야 합니다.

광고 계정 연결이나 Google의 사이트 승인은 GitHub Pages의 상업 이용을 허가하는 절차가 아닙니다. 실제 광고를 켜기 전에는 [기존 호스팅·광고 연결 안내](../AD-MONETIZATION.md)를 확인해야 합니다.

참고: [GitHub 사용자 사이트 만들기](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site), [AdSense 사이트 소유권 확인](https://support.google.com/adsense/answer/7584263)
