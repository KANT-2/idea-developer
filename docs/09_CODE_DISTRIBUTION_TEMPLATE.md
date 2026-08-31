# 09. 팀원에게 코드를 전달하는 양식

팀장은 AI에게 받은 코드를 아래 양식으로 나눠 팀원에게 보냅니다.

```text
[작업 번호] STEP-01-FILE-03
[담당자] GitHub ID
[기준 브랜치] develop
[만들 브랜치] setup/config-settings
[새로 만들 파일] config/settings.py
[먼저 merge되어야 하는 작업] STEP-01-FILE-01 config/__init__.py
[파일에 붙여넣을 전체 코드] --- 코드 시작 --- ... --- 코드 끝 ---
[확인 명령] python -m compileall config/settings.py
[commit 메시지] chore: Django 기본 설정 파일 추가
[PR 대상] develop
```

## 팀원이 실행할 명령

```bash
git switch develop
git pull origin develop
git switch -c setup/config-settings
```

전달받은 경로에 파일을 만들고 전체 코드를 붙여넣은 뒤:

```bash
git status
git diff -- config/settings.py
git add config/settings.py
git commit -m "chore: Django 기본 설정 파일 추가"
git push -u origin setup/config-settings
```

GitHub에서 `develop` 대상 PR을 만듭니다.

## 팀장이 AI에게 요청할 출력 형식

```text
이번 단계의 코드를 바로 수정하지 말고 먼저 파일별 전달 패킷으로 나눠줘.
각 패킷에 작업 번호, 정확한 파일 경로, 파일 전체 코드, 의존 작업 번호,
권장 branch 이름, commit 메시지, 확인 명령을 포함해줘.
이미 만들어 둔 폴더 구조를 바꾸지 마.
서로 강하게 의존해 단독 merge가 위험한 파일은 같은 패킷으로 묶고 이유를 알려줘.
```

## 주의

- 새 파일은 일부 조각이 아니라 전체 내용을 전달합니다.
- 기존 파일 수정은 diff와 적용 위치를 함께 전달합니다.
- 동일 파일을 두 팀원에게 동시에 배정하지 않습니다.
- 비밀값은 코드 패킷에 넣지 않습니다.
- 파일이 모두 모이기 전 단독 실행이 불가능할 수 있으므로 단계 완료 후 통합 테스트합니다.
