# 3조 소스 전달 양식

4조 통합 저장소에 전달할 때 아래 항목을 빠짐없이 작성합니다. 실제 비밀번호와 API 키는
기록하지 않고 필요한 환경변수 이름만 전달합니다.

```text
Base Branch:
Base Commit SHA:
Work Branch:
Latest Commit SHA:

변경 파일 목록:
-

Migration 변경 여부:
- 없음 / 있음
- 추가 migration:
- 적용 명령: python manage.py migrate
- 데이터 보존 또는 사전 확인 사항:

requirements 변경 여부:
- 없음 / 있음
- 추가·변경 패키지:

추가 환경변수:
- 없음 / 변수 이름과 용도

외부 연동:
- PostgreSQL VIEW:
- Slack notifications 모듈:
- Gemini:

테스트 결과:
- python manage.py check --settings=config.settings.test
- python manage.py makemigrations --check --dry-run --settings=config.settings.test
- python manage.py test --settings=config.settings.test
- ruff format --check .
- ruff check .

미구현·보류·부모팀 결정 필요 사항:
-
```

## 전달 전 확인

- 작업 브랜치를 원격에 push하고 위 SHA를 `git rev-parse`로 다시 확인합니다.
- migration 순서와 부모 앱 migration 충돌 여부를 확인합니다.
- `.env`, 실제 DB 비밀번호, Gemini 키, 개인정보가 commit되지 않았는지 확인합니다.
- 부모 프로젝트에서 사용하는 `accounts_user.id`와 자식의 외부 `user_id` 계약을 확인합니다.
- 브레인스토밍 React CDN origin을 부모 CSP에 반영해야 하는지 확인합니다.
