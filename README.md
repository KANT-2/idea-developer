# Idea Developer

아이디어 디벨로퍼를 독립 Django 시스템으로 개발하는 팀 저장소입니다.

- Backend: Django 5.2.x
- UI: Django Template + Bootstrap 5.3.2
- Database: PostgreSQL
- 브레인스토밍 UI: React·ReactDOM CDN
- 사용자·회차·팀: 제공된 PostgreSQL VIEW 읽기 전용 조회
- 협업 갱신: HTTP polling + version 충돌 검사
- 백그라운드 작업: PostgreSQL 작업 테이블 + Django management command worker

부모 프로젝트의 테스트용 `ideas` 앱은 확정 구현이 아닙니다. 이 저장소에서는 독립 시스템을 완성하며, 부모 프로젝트 이식은 부모 운영 팀이 담당합니다.

## 처음 시작하기

처음 참여한다면 아래 문서를 순서대로 읽으세요.

1. [프로젝트 시작 안내](docs/00_START_HERE.md)
2. [개발 환경 설치](docs/01_LOCAL_SETUP.md)
3. [Git과 GitHub 작업 흐름](docs/02_GIT_WORKFLOW.md)
4. [브랜치·커밋·Pull Request](docs/03_BRANCH_COMMIT_PR.md)
5. [프로젝트 구조](docs/04_PROJECT_STRUCTURE.md)
6. [팀 코드 분배표](docs/05_TEAM_TASKS.md)
7. [문제 해결](docs/06_TROUBLESHOOTING.md)
8. [AI 코딩 규칙](docs/07_AI_CODING_RULES.md)
9. [부모 팀 이관 메모](docs/08_PARENT_HANDOFF.md)
10. [코드 전달 양식](docs/09_CODE_DISTRIBUTION_TEMPLATE.md)
11. [저장소 관리자 설정](docs/10_REPOSITORY_OWNER_SETUP.md)

## 가장 중요한 규칙

- `main`에서 직접 작업하거나 push하지 않습니다.
- 작업 하나마다 새 브랜치를 만듭니다.
- 작은 단위로 commit하고 GitHub에 push합니다.
- Pull Request(PR)를 열고 팀원 한 명의 확인을 받은 뒤 merge합니다.
- `.env`, 비밀번호, API 키, 실제 사용자 데이터는 절대 commit하지 않습니다.
- 다른 사람 파일을 임의로 덮어쓰지 않습니다.

## 현재 상태

백엔드 프로젝트 뼈대가 준비되어 있습니다. 제품 테이블, 제품 API, 실제 AI 호출은 아직 구현하지 않았습니다. 기준 정책은 `docs/specs/home-backend-scenario.md`와 `docs/specs/brainstorm-backend-scenario.md`입니다.

## 로컬 실행

Python 3.12 이상과 PostgreSQL이 필요합니다. PowerShell 기준 예시입니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements/development.txt
Copy-Item .env.example .env
```

PostgreSQL에서 로컬 사용자와 `idea_developer` 데이터베이스를 준비한 뒤 `.env`의 접속값을 수정합니다. 애플리케이션 schema는 다음 명령으로 생성합니다.

```powershell
psql -U idea_developer -d idea_developer -f scripts/bootstrap_database.sql
python manage.py migrate
python manage.py runserver
```

헬스체크는 인증 없이 배포 상태를 확인하기 위한 유일한 공개 API입니다.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/
```

## 테스트와 코드 품질

테스트 설정은 외부 DB 쿼리가 없는 단위 테스트에 PostgreSQL 접속을 요구하지 않습니다.

```powershell
python manage.py check --settings=config.settings.test
python manage.py test --settings=config.settings.test
ruff format --check .
ruff check .
```

자동 포매팅은 `ruff format .`으로 실행합니다.

## 백그라운드 worker

작업 테이블 상태 계약이 기준 문서에서 확정되기 전까지 worker는 등록된 작업 없이 안전하게 대기하는 구조만 제공합니다.

```powershell
python manage.py run_job_worker
python manage.py run_job_worker --once
```

향후 승인된 PostgreSQL 작업 테이블 구현은 `JOB_RUNNER_CLASS` 설정으로 연결합니다. Redis, Celery, Django Channels는 필수 의존성이 아닙니다.

## UI와 부모 이관 지점

- `templates/base.html`은 Bootstrap `5.3.2`와 `extra_head`, `breadcrumb`, `content`, `modals`, `extra_js` block을 사용합니다.
- `templates/brainstorm/shell.html`은 `#brainstorm-root`만 제공하며 React와 ReactDOM `18.3.1`을 고정 CDN으로 불러옵니다.
- `static/brainstorm/js/app.js`는 JSX와 브라우저 Babel 변환을 사용하지 않습니다.
- 부모 이관 시 `https://cdn.jsdelivr.net`을 CSP `script-src`와 필요한 `style-src`에 반영해야 합니다.
- CSRF 토큰은 base template의 meta에 노출됩니다. API 호출은 같은 origin의 session cookie와 `X-CSRFToken` 헤더를 사용해야 하며 서버에서 로그인·권한을 다시 검사합니다.

## 독립 연동 경계

`apps.integration.context`는 로컬 로그인 사용자를 외부 `user_id`와 현재 `round_id`, `team_id` 문맥으로 바꾸는 adapter 계약을 제공합니다. `public.ax_user_team_login_view`와 `public.user_round_team_view`는 `managed=False` 모델과 전용 repository로만 조회합니다. ORM 쓰기 메서드와 DB router가 INSERT·UPDATE·DELETE를 차단하며, 별도 DB 연결에는 PostgreSQL `default_transaction_read_only=on`을 적용합니다.

`.env`에 부모 VIEW용 읽기 전용 계정과 부모 시스템에서 실제 사용하는 진행 중 회차 상태값을 설정합니다. 기준 문서에는 해당 상태 문자열이 없으므로 임의 기본값을 제공하지 않습니다.

```text
INTEGRATION_DB_NAME=ax_evaluation
INTEGRATION_DB_USER=<읽기 전용 계정>
INTEGRATION_ACTIVE_ROUND_STATUSES=<부모가 확인한 실제 상태값>
```

회차 확인 화면은 `/integration/round/`입니다. 단일 진행 회차는 자동 확인하고, 없으면 회차 없음 화면, 여러 개면 선택 화면을 표시합니다. URL·form·session의 `round_id`는 항상 `user_round_team_view`의 `user_id + round_id`로 다시 검증합니다. VIEW 장애나 중복 팀 데이터가 발생하면 `503`으로 fail closed하며, 참가하지 않은 회차는 `403`을 반환합니다.

`apps/integration/migrations/0001_initial.py`는 unmanaged Django model state만 기록합니다. `RunSQL`이나 VIEW 생성·수정 SQL은 포함하지 않으며 부모 VIEW의 생명주기를 소유하지 않습니다.

협업 polling 간격은 `.env`에서 설정합니다. 실제 polling endpoint와 version 충돌 응답은 제품 리소스·version 필드 정책이 승인된 뒤 추가합니다.

## 설정 구분

- 기본: `config.settings.base`
- 개발: `config.settings.development` (manage.py 기본값)
- 테스트: `config.settings.test`
- 운영: `config.settings.production`

운영에서는 `DJANGO_SECRET_KEY`, PostgreSQL 비밀번호, 외부 서비스 키를 환경변수나 비밀 저장소로만 주입합니다. 저장소에는 실제 비밀값을 넣지 않습니다.
