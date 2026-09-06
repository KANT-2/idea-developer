# 10. 저장소 관리자 설정

이 문서는 저장소 소유자가 팀원을 초대하고 작업을 운영하는 방법입니다.

## 1. 팀원 초대

GitHub 저장소에서 다음 순서로 이동합니다.

```text
Settings → Collaborators → Add people
```

팀원의 GitHub ID 또는 이메일을 검색해 초대합니다. 팀원은 이메일이나 GitHub 알림에서 초대를 수락해야 clone과 push가 가능합니다.

초대 전에는 팀원에게 비밀번호나 개인 access token을 받지 않습니다. 각자 자기 GitHub 계정으로 접속합니다.

## 2. 브랜치 역할

- `main`: 단계별 안정 버전
- `develop`: 파일별 코드를 조립하는 브랜치
- 개인 branch: 팀원이 전달받은 파일을 추가하는 배정 브랜치

현재 배정 브랜치는 `heeju`, `yg`, `dara`, `hyungjune`, `sungho`, `nakyoung`입니다. 팀원은 작업 전
`develop`을 최신화해 자기 브랜치에 병합하고 PR 대상은 `develop`으로 선택합니다. 팀장은 단계
전체가 실행되고 테스트가 통과한 뒤 `develop → main` PR을 만듭니다.

## 3. 팀원에게 처음 보낼 메시지

```text
1. GitHub 저장소 초대를 수락해 주세요.
2. https://github.com/KANT-2/idea-developer 를 clone해 주세요.
3. README와 docs/00_START_HERE.md부터 읽어 주세요.
4. 코드는 제가 보내는 파일 경로와 전체 내용을 그대로 추가합니다.
5. develop을 최신화해 배정된 개인 branch에 병합한 뒤 develop 대상 PR을 열어 주세요.
6. .env와 비밀번호는 절대 commit하지 마세요.
```

## 4. 파일 전달 전 확인

- 동일 파일을 다른 팀원에게 이미 배정하지 않았는가
- 의존 파일이 `develop`에 먼저 merge됐는가
- 정확한 브랜치명·파일 경로·commit 메시지를 보냈는가
- 코드에 비밀값이나 실제 사용자 데이터가 없는가
- 새 파일의 전체 코드를 보냈는가

## 5. 팀원 PR 확인

GitHub PR 화면에서 base가 `develop`인지 확인합니다. `Files changed`에서 배정한 파일 외 변경이 없는지 보고, 가능한 검사 명령 결과를 확인합니다.

파일 하나만으로 실행되지 않는 단계는 문법과 경로를 먼저 확인하고 의존 순서대로 merge합니다. 마지막 파일까지 모인 후 팀장이 전체 검사를 실행합니다.

```bash
git switch develop
git pull origin develop
python manage.py check
python manage.py test
```

## 6. 단계 완료

1. `develop`에서 전체 검사와 테스트를 통과시킵니다.
2. GitHub에서 `develop → main` PR을 만듭니다.
3. 단계에서 구현된 기능과 테스트 결과를 적습니다.
4. 팀원 리뷰 후 merge합니다.
5. 다음 작업 전에 각 팀원 branch에 최신 `develop`을 다시 병합합니다.

## 7. 권장 GitHub 설정

팀원 초대 후 `Settings → Branches` 또는 `Rules → Rulesets`에서 `main`과 `develop`에 직접 push를 막고 PR을 요구하는 규칙을 설정합니다.

- Pull Request 필수
- 승인 1명 이상
- force push 금지
- branch 삭제 금지
- 대화가 해결된 뒤 merge

현재 `.github/workflows/quality.yml`의 `Quality / test`가 Pull Request와 `develop`, `main` push에서
실행됩니다. PostgreSQL 16 전체 테스트, 85% 코드 커버리지, Ruff, migration 일관성과 운영 배포
설정을 검사하므로 branch protection의 필수 status check로 `Quality / test`를 지정합니다.

관리자 우회 병합은 긴급 복구처럼 명확한 사유가 있을 때만 사용합니다. 일반 변경은 CI 통과와
요구된 리뷰를 받은 뒤 병합하고, 실패한 검사를 우회하지 않습니다.
