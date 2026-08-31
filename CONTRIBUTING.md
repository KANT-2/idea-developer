# 협업 규칙

## 작업 시작 전

```bash
git switch develop
git pull origin develop
git switch -c <종류>/<짧은-작업명>
```

브랜치 예시:

- `feat/login-ui`
- `feat/home-kpi`
- `fix/otp-expiration`
- `test/prd-permission`
- `docs/jiwon-git-practice`

## 작업 중

```bash
git status
git diff
git add <내가-수정한-파일>
git commit -m "feat: 로그인 이메일 입력 화면 추가"
```

`git add .`는 관계없는 파일까지 포함할 수 있으므로 초반에는 파일명을 직접 적습니다.

## GitHub에 올리기

```bash
git push -u origin <현재-브랜치명>
```

GitHub에서 base branch를 `develop`으로 선택해 Pull Request를 만들고 다음을 적습니다.

- 무엇을 바꿨는지
- 왜 바꿨는지
- 어떻게 확인했는지
- 화면 변경이면 스크린샷
- 아직 남은 문제

## 리뷰와 merge

- 작성자는 자기 PR을 바로 merge하지 않습니다.
- 리뷰어는 코드와 테스트를 확인한 뒤 승인하거나 수정 요청을 남깁니다.
- 수정 요청은 같은 브랜치에 새 commit으로 push합니다.
- 승인 뒤 GitHub의 `Squash and merge`를 기본으로 사용합니다.
- merge 후 로컬 브랜치를 정리합니다.

```bash
git switch main
git pull origin main
git branch -d <작업-브랜치명>
```

## 금지 사항

- `main`, `develop` 직접 push
- 공유 브랜치에서 `git push --force`
- `.env`, DB 비밀번호, 사용자 개인정보 commit
- 팀장이 전달하지 않은 파일을 임의로 추가하거나 수정
- 테스트 실패 상태로 merge
