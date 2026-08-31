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
- 개인 branch: 팀원이 전달받은 파일을 추가하는 브랜치

팀원은 `develop`에서 branch를 만들고 PR 대상도 `develop`으로 선택합니다. 팀장은 단계 전체가 실행되고 테스트가 통과한 뒤 `develop → main` PR을 만듭니다.

## 3. 팀원에게 처음 보낼 메시지

```text
1. GitHub 저장소 초대를 수락해 주세요.
2. https://github.com/kixxuya/idea-developer 를 clone해 주세요.
3. README와 docs/00_START_HERE.md부터 읽어 주세요.
4. 코드는 제가 보내는 파일 경로와 전체 내용을 그대로 추가합니다.
5. 항상 develop에서 개인 branch를 만든 뒤 develop 대상 PR을 열어 주세요.
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
5. 다음 단계의 팀원 branch는 최신 `develop`에서 다시 만듭니다.

## 7. 권장 GitHub 설정

팀원 초대 후 `Settings → Branches` 또는 `Rules → Rulesets`에서 `main`과 `develop`에 직접 push를 막고 PR을 요구하는 규칙을 설정합니다.

- Pull Request 필수
- 승인 1명 이상
- force push 금지
- branch 삭제 금지
- 대화가 해결된 뒤 merge

초기 파일 조립 중에는 필수 CI 검사를 아직 지정하지 않습니다. 테스트 workflow가 추가된 뒤 status check를 필수로 바꿉니다.
