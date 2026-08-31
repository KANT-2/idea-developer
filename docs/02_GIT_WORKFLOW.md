# 02. Git과 GitHub 작업 흐름

## Git과 GitHub의 차이

- Git: 내 컴퓨터에서 파일 변경 이력을 저장하는 도구
- GitHub: Git 저장소를 팀원과 공유하고 리뷰하는 서비스
- commit: 내 컴퓨터에 저장한 변경 묶음
- push: 내 commit을 GitHub로 전송
- pull: GitHub의 최신 변경을 내 컴퓨터로 가져오기
- branch: main을 건드리지 않고 작업하는 별도 작업선
- Pull Request: 내 branch를 main에 합쳐 달라는 요청

## 매 작업의 표준 명령

```bash
git switch develop
git pull origin develop
git switch -c feat/작업명
```

파일을 수정한 뒤:

```bash
git status
git diff
git add path/to/file.py
git commit -m "feat: 변경 내용을 한글로 명확히 작성"
git push -u origin feat/작업명
```

그 다음 GitHub에서 `develop`을 대상으로 PR을 엽니다.

## 새 작업마다 새 branch를 쓰는 이유

- 다른 사람 작업과 섞이지 않습니다.
- 문제가 생기면 branch만 버릴 수 있습니다.
- PR에서 변경 내용을 이해하기 쉽습니다.
- 동시에 여러 명이 작업할 수 있습니다.

## main과 develop의 역할

- `main`: 한 단계가 완성되고 테스트가 통과한 안정 버전
- `develop`: 팀원 파일을 모아 다음 단계를 조립하는 브랜치
- 개인 작업 branch: 전달받은 파일을 추가하는 공간

파일별 PR은 `develop`에 합치고, 한 단계의 모든 파일이 모여 테스트가 통과하면 팀장이 `develop → main` PR을 만듭니다.

## 다른 팀원의 변경 가져오기

```bash
git switch develop
git pull origin develop
```

작업 branch에 최신 develop을 반영해야 한다면:

```bash
git switch <내-브랜치>
git merge develop
```

초보 단계에서는 rebase보다 merge를 먼저 사용합니다.

## 작업을 잠시 보관하기

commit 전 다른 branch로 급히 이동해야 할 때만 사용합니다.

```bash
git stash push -m "로그인 화면 작업 중"
git stash list
git stash pop
```

stash에 오래 보관하지 말고 가능한 작은 임시 commit을 권장합니다.
