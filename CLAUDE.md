# edtech — 교육방법및교육공학 수업자료

임태형 교수의 교육방법및교육공학 강의 자료 저장소. 원본 자료·제작 산출물·공개 배포본이 모두 여기 있다.

## ⚠️ 이 저장소는 PUBLIC 이다

`github.com/taehyeonglim/edtech` — 커밋되는 모든 것은 공개된다. 마크다운 소스도 마찬가지다.

**절대 커밋하면 안 되는 것** (`.gitignore`로 차단되어 있음 — 규칙을 지우거나 `git add -f` 하지 말 것):

| 경로 | 이유 |
|---|---|
| `Previous_lecture_content/` | PI 사적 강의자료. 학기별 gslides/pptx/pdf + 학지사 교재 목차 `.hwp` — **저작권 자료** |
| `content/` | 에이전트 제작 툴의 로컬 작업 산출물 (composed.md, DESIGN.md, 검수 리포트, 중간 deck/이미지) |
| `docs-internal/` | 내부 spec·plan·핸드오프 (목차의 저작권 재구성 근거 등 내부 판단 기록) |
| `site/`, `.gjc/` | 빌드 산출물, 세션 로그 |

커밋 전 확인: `git status --short` 에 위 경로가 하나도 안 보여야 한다.

## 클론 위치

정본은 **이 폴더** (`~/Documents/GitHub/edtech`). 2026-08-05 이전 문서에 나오는 `~/edtech`는 폐기됐고 `~/edtech-backup-2026-08-05`로 보존만 되어 있다 — **거기서 작업하지 말 것.** 새로 clone 하지도 말 것(세 번째 사본이 생긴다).

## 구조

| 경로 | 역할 | 공개 |
|---|---|---|
| `index.html` | 랜딩 허브 (교재/슬라이드 두 갈래) | ✅ |
| `docs/` | MkDocs 교재 소스 — `index.md` + `part1~4/ch01~11.md` (본문 집필 완료) | ✅ |
| `mkdocs.yml` | MkDocs Material 설정 (한국어 UI) | ✅ |
| `book/`, `book-reader/`, `assets/` | 페이지 넘김 리더 (page-flip) | ✅ |
| `tools/` | 리더 생성·검증 파이썬 스크립트 | ✅ |
| `chapters/chapter-NN/` | 공개 슬라이드 — `slides/deck.{html,pdf}` + `images/` 만 화이트리스트 | ✅ |
| `Previous_lecture_content/` | 원본 강의자료 (제작 입력) | ❌ |
| `content/chapters/` | 제작 산출물 스냅샷 — 교재 집필의 디딤돌 `composed.md` 등. **읽기 전용**(아래 참조) | ❌ |
| `docs-internal/` | spec·plan·핸드오프 | ❌ |

## 배포

`main` 에 push 하면 GitHub Actions(`.github/workflows/deploy.yml`)가 자동 배포한다. 수동 빌드·복사 불필요.

```bash
python3 -m mkdocs build --strict   # 커밋 전 필수 — 깨진 링크/문법 검출
git push origin main               # → 1~2분 후 https://taehyeonglim.github.io/edtech/ 반영
```

- `.github/workflows/` 를 수정할 때만 `gh auth refresh -h github.com -s workflow` 필요. 그 외 push 는 일반 권한으로 충분.
- **배포가 `Deployment failed, try again later`(syncing_files 단계)로 실패하면** GitHub Pages 인프라의 일시 오류다. 코드 문제가 아니므로 **빈 커밋을 만들지 말고 워크플로만 재실행**한다: `gh workflow run "Deploy edtech site" --repo taehyeonglim/edtech` (2026-07-04에 실제로 이 경로로 복구됨).
- mkdocs 로컬 설치(Homebrew Python, PEP 668): `python3 -m pip install --user --break-system-packages mkdocs-material`
- 배포 확인: `gh run list --repo taehyeonglim/edtech -L1`

## 저작권 원칙

학지사 교재의 구조·개념 흐름은 참고하되 **본문을 그대로 옮기지 않는다.** 장·절 명칭도 독자 명칭을 쓴다(현재 목차는 이미 그렇게 설계됨). 자세한 배경은 `docs-internal/specs/2026-06-14-edtech-docs-site-design.md`.

## 작업 방식

**이 저장소에서 Claude Code 또는 Codex로 직접 작업한다.** tmux 다중 pane 에이전트 팀은 2026-08-05부로 쓰지 않는다.

`content/chapters/`는 그 에이전트 팀이 남긴 **영구 동결 스냅샷**이다. 교재 집필의 디딤돌로 **읽는 용도**이며, 여기에 새 챕터가 자동 생성되는 일은 없다. 슬라이드를 새로 만들거나 고쳐야 하면 `chapters/chapter-NN/slides/deck.html`을 직접 편집한다.

### 은퇴한 저장소

`~/Documents/GitHub/lecture-content-maker-agent-team` — 슬라이드를 만들던 Claude Code 5-에이전트 팀 툴. 원본 자료와 산출물이 이 저장소로 이관되면서 그쪽 `scripts/*.sh`·`dashboard/`·`.claude/agents/`의 상대경로 참조는 전부 깨졌고, **복구할 계획은 없다.** 참고용으로만 남아 있다.
