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

독립 Django 시스템의 PRD·홈·브레인스토밍·AI 작업 기반이 구현되어 있습니다. 실제 외부 AI
제공자와 운영 프롬프트는 승인된 모델·프롬프트를 환경과 DB에 등록하기 전까지 비활성 상태입니다.
기준 정책은 `docs/specs/home-backend-scenario.md`와
`docs/specs/brainstorm-backend-scenario.md`입니다.

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

테스트 설정은 자식 소유 인증 테이블에 메모리 SQLite를 사용하고 부모 VIEW는 fixture repository로 대체하므로 PostgreSQL 접속을 요구하지 않습니다. 운영 스택과 실제 migration 대상은 PostgreSQL입니다.

```powershell
python manage.py check --settings=config.settings.test
python manage.py test --settings=config.settings.test
ruff format --check .
ruff check .
```

자동 포매팅은 `ruff format .`으로 실행합니다.

## 백그라운드 worker

AI 요청은 웹 프로세스가 PostgreSQL `ai_jobs` 테이블에 등록하고, 별도 management command
프로세스가 행 잠금과 lease를 사용해 하나씩 처리합니다. Redis와 Celery는 사용하지 않습니다.

```powershell
python manage.py run_job_worker
python manage.py run_job_worker --once
```

기본 `AI_PROVIDER_CLASS`는 Gemini Developer API 어댑터입니다. Google AI Studio에서 발급한
키를 개인 `.env` 또는 배포 비밀 저장소의 `GEMINI_API_KEY`에만 주입합니다. 키가 비어 있으면
worker는 외부 요청 없이 작업을 안전하게 실패 처리합니다. 사용할 Gemini 모델명은 기능별 활성
`AI_Prompts.model`에 저장하므로 코드에 고정하지 않습니다. timeout, 최대 재시도, 재시도 간격과
일일 요청·토큰·비용 제한은 `.env.example`의 `AI_*` 설정으로 관리합니다.

Gemini 요청은 API 키를 URL이 아닌 `x-goog-api-key` 헤더로 전송하고, 시스템 지시와 신뢰하지
않는 사용자 JSON을 서로 다른 영역으로 전달합니다. 구조화 출력은 Gemini에 JSON Schema로
요청한 뒤 자식 시스템의 전체 Schema와 DB 식별자 검증을 다시 통과해야 성공합니다. 무료 등급의
모델·요청 한도는 계정과 시점에 따라 달라질 수 있으므로 수치를 코드에 고정하지 않으며,
`429 RESOURCE_EXHAUSTED`는 제한된 횟수 안에서 재시도합니다.

Google의 현재 안내상 Gemini 무료 등급에 전송한 콘텐츠는 제품 개선에 사용될 수 있습니다.
민감정보나 비공개 고객 데이터를 보내기 전에는 팀의 데이터 처리 정책을 먼저 확정해야 합니다.

작업은 `queued`, `running`, `retry_wait`, `cancel_requested`, `succeeded`, `failed`,
`cancelled`, `timed_out` 상태를 사용합니다. worker 중단으로 lease가 만료된 작업은 다음 worker가
재시도하거나 최종 시간 초과로 닫습니다. 성공·실패·취소된 실제 실행은 `ai_usage_logs`에 별도로
기록하며 프롬프트 정의 행은 사용 횟수로 집계하지 않습니다.

## PRD AI 코치와 질문 초안

PRD 작성 화면은 `/ideas/prds/<prd_id>/`입니다. AI 코치 대화는 PRD·섹션·사용자별로
분리되며 전체 PRD 대화는 section 없이 저장합니다. 화면에서는 범위를 바꿀 때 해당 대화를
다시 불러오고, 저장된 전체 메시지를 보여 줍니다. 모델에는 완료된 최근 3턴과 크기가 제한된
PRD Context만 전달합니다.

코치와 초안 요청은 PostgreSQL AI 작업으로 등록되므로 별도 worker가 실행 중이어야 합니다.
활성 `COACHING` 프롬프트의 JSON Schema는 코치 결과 `{ "message": "..." }`와 질문 초안 결과
`{ "question_id": 1, "draft": "..." }`를 허용해야 합니다. 질문 초안은 작업 결과로만 반환되며,
미리보기에서 수정하고 반영 API를 호출하기 전에는 PRD 답변을 변경하지 않습니다.

- 대화: `GET /api/v1/prds/<prd_id>/ai/conversation/`
- 코치 요청: `POST /api/v1/prds/<prd_id>/ai/chat/`
- 초안 요청: `POST /api/v1/prds/<prd_id>/ai/drafts/`
- 작업 조회·취소·재시도: `/api/v1/prds/<prd_id>/ai/jobs/<job_id>/...`
- 초안 반영: `POST /api/v1/prds/<prd_id>/ai/drafts/<job_id>/apply/`

초안 생성 당시 질문 version과 현재 version이 다르면 반영 API는 `409 Conflict`를 반환합니다.
대화 만료 시각은 메시지를 저장할 때마다 30일 뒤로 갱신되며 worker가 만료 대화를 삭제합니다.

## 브레인스토밍 AI 분석과 항목 분류

브레인스토밍 화면에서 분석과 분류 요청도 PostgreSQL AI 작업으로 등록합니다. 분석의 전체·채택·
보류·미분류 및 섹션별 개수는 서버가 요청 시점의 데이터로 계산하며 AI 응답의 개수는 저장하거나
표시하지 않습니다. 활성 일반 메모가 없는 캔버스는 AI를 호출하지 않습니다.

- 분석 요청: `POST /api/v1/prds/<prd_id>/brainstorm/ai/analysis/`
- 분류 요청: `POST /api/v1/prds/<prd_id>/brainstorm/ai/classification/`
- 작업 조회·취소·재시도: `/api/v1/prds/<prd_id>/brainstorm/ai/jobs/<job_id>/...`
- 선택 분류 반영: `POST /api/v1/prds/<prd_id>/brainstorm/ai/classification/apply/`

활성 `BRAINSTORM_ANALYSIS` 프롬프트는 `summary`, `section_findings[]`, `missing_topics[]`,
`source_node_ids[]`를 요구하는 JSON Schema를 사용합니다. 활성 `BRAINSTORM_CLASSIFICATION`
프롬프트는 `recommendations[]` 안에 `node_id`, `section_id`, `reason`을 요구하는 JSON Schema를
사용합니다. AI가 반환한 노드·섹션 ID는 요청 snapshot 및 현재 DB와 다시 대조합니다.

분류 요청에는 삭제되지 않고 보류되지 않은 미분류 일반 메모와 현재 PRD 섹션만 전달됩니다.
추천은 미리보기일 뿐 데이터를 변경하지 않으며, 사용자가 선택한 항목만 version 검사를 거쳐 한
트랜잭션으로 반영합니다. 하나라도 충돌하면 전체 반영을 취소하고 `409 Conflict`와 최신 노드를
반환합니다. 요청과 반영 API는 각각 `Idempotency-Key` 헤더를 사용합니다.

## AI PRD 반영

브레인스토밍 화면에서 전체 PRD 또는 한 섹션을 선택해 통합 답변 미리보기를 만들 수 있습니다.
채택 메모는 자동 포함하고, 섹션이 지정된 기본 메모는 사용자가 체크한 경우에만 추가합니다.
보류·삭제 메모와 미분류 채택 메모는 자동 반영하지 않습니다.

- 미리보기: `POST /api/v1/prds/<prd_id>/brainstorm/ai/prd-apply/preview/`
- 질문별 승인 반영: `POST /api/v1/prds/<prd_id>/brainstorm/ai/prd-apply/apply/`

미리보기는 기존 답변, 통합 초안, 근거 메모, 유지·추가된 내용, 미사용 메모, 경고와 신뢰도를
반환하며 기존 답변을 변경하지 않습니다. 반영 요청은 `preview_request_id`, 전체 노드별 version,
승인할 질문 ID와 version을 보내야 합니다. 한 항목이라도 미리보기 이후 바뀌면 전체 트랜잭션을
취소하고 `409 Conflict`를 반환합니다.

승인된 질문만 저장하고 같은 `Idempotency-Key` 요청은 최초 결과를 다시 반환합니다. 적용 기록은
`ai_prd_apply_records`와 `ai_prd_apply_items`에 실행 사용자, 모델·프롬프트 버전, 기존·통합 답변,
질문 version, 근거 노드와 노드 version을 보존합니다.

## PRD 완료와 재개

- 완료: `POST /api/v1/prds/<prd_id>/complete/`
- 재개: `POST /api/v1/prds/<prd_id>/reopen/` body `{ "reason": "재개 이유" }`

완료는 owner만 수행합니다. 미완료 질문이 있으면 먼저 경고하며, 사용자가 확인한 재요청에
`{ "confirm_incomplete": true }`를 보내야 합니다. 완료된 PRD는 답변, 브레인스토밍 데이터,
연결선, AI PRD 반영과 일반 코멘트를 서버에서 잠급니다. tutor만
`post_completion_review` 코멘트를 작성할 수 있으며 이 코멘트는 기여도에서 제외됩니다.

재개는 owner 또는 IntegrationContext의 staff/superuser 관리자만 수행할 수 있습니다. 재개 이유,
실행 사용자와 이전 완료 시각은 `prd_status_audit_logs`에 보존하고 일반 변경 이력에도 상태 전환을
남깁니다.

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

## 이메일 인증 로그인

독립 로그인은 회원가입과 비밀번호 없이 6자리 일회용 인증번호를 사용합니다.

- 로그인 화면: `/accounts/login/`
- 인증번호 요청: `POST /api/v1/auth/otp/request/`
- 인증번호 검증: `POST /api/v1/auth/otp/verify/`
- 로그아웃: `POST /accounts/logout/`
- 회차 참가자 검색: `GET /api/v1/users/search/`

인증번호는 해시만 저장하며 기본 10분 만료, 1회 사용, 5회 실패 제한, 60초 재전송 제한을 적용합니다. 이메일·IP 요청 제한 값은 `OTP_*` 환경변수에서 조정합니다. 미등록·비활성·미승인 이메일에도 동일한 요청 성공 문구를 반환합니다.

`LocalUserMapping`은 Django session을 위한 최소 매핑입니다. `external_user_id`, 이메일 snapshot, 로컬 차단 상태와 마지막 검증 시각만 사용자 연동 정보로 가지며 비밀번호는 항상 unusable입니다. 이름·역할·팀·회차·프로필은 계속 부모 VIEW를 진실의 원천으로 사용합니다. 로그인 성공·실패와 로그아웃은 부모 VIEW의 `last_login`을 수정하지 않고 자식 `LoginAuditLog`에 기록합니다.

운영에서는 실제 메일 발송 backend와 SMTP 비밀값을 환경변수로 설정해야 합니다. console·메모리·dummy backend가 `DEBUG=false`에서 설정되면 배포 검사 `accounts.E002`가 실패합니다.

`DEBUG=true`에서만 `/accounts/dev/login/`이 URL에 등록됩니다. 이 화면은 검색어 입력 후 활성·승인 사용자 일부만 페이지 단위로 조회합니다. 운영 배포 검사 `accounts.E001`은 `DEBUG=false`에서 해당 URL이 잘못 등록되면 실패합니다.

## 역할 권한 정책

`apps/accounts/permissions.py`가 `owner`, `editor`, `tutor`, `viewer`의 서버 권한 행렬을 한 곳에서 관리합니다. 완료 상태에서는 owner의 재개와 tutor의 리뷰 코멘트만 상태 변경 예외로 허용합니다. 실제 PRD 참여 관계는 PRD 구현 단계에서 외부 `user_id`, `round_id`, `participant_id`, `team_id`와 함께 저장합니다.

부모 `role`, `is_staff`, `is_superuser` 자동 매핑은 아직 확정되지 않았으므로 기본값이 없습니다. 확정 후 아래 환경변수만 설정합니다.

```text
PARENT_ROLE_PARTICIPANT_MAP={"student":"editor","tutor":"tutor"}
PARENT_STAFF_PARTICIPANT_ROLE=tutor
PARENT_SUPERUSER_PARTICIPANT_ROLE=owner
```

위 값은 예시이며 승인된 정책 없이 운영 설정에 사용하지 않습니다.

> 기존 프로젝트 뼈대에서 이미 `migrate`를 실행한 로컬 DB가 있다면 주의하세요. 이번 단계에서 최초 custom user model이 도입되었으므로 기존 기본 `auth.User` migration 이력이 있는 DB는 그대로 전환하지 않습니다. 필요한 데이터를 백업하고 새 개발 DB/schema를 준비한 뒤 migration해야 하며, 자동 삭제는 수행하지 않습니다.

## 설정 구분

- 기본: `config.settings.base`
- 개발: `config.settings.development` (manage.py 기본값)
- 테스트: `config.settings.test`
- 운영: `config.settings.production`

운영에서는 `DJANGO_SECRET_KEY`, PostgreSQL 비밀번호, 외부 서비스 키를 환경변수나 비밀 저장소로만 주입합니다. 저장소에는 실제 비밀값을 넣지 않습니다.
