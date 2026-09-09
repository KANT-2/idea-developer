# idea-developer 현재 소스 전달 명세

이 문서는 독립 `idea-developer`를 부모 Django 시스템에 통합할 때 함께 전달할 현재 구현
명세입니다. 실제 비밀번호, API 키, 사용자 데이터와 로컬 데모 산출물은 전달 대상이 아닙니다.

## 1. 소스 기준점

| 항목 | 값 |
|---|---|
| Source repository | `KANT-2/idea-developer` |
| Base branch | `develop` |
| 문서 갱신 직전 기능 기준 commit | `4c18a0e75828c05c871c1e6d21362f5b5922443d` |
| Work branch | `heeju` |
| 최종 전달 branch | `develop` |
| Target repository | `KANT-2/review-system` |
| Target branch | 부모 통합팀이 전달 시 지정한 branch |

이 문서를 갱신한 최종 merge commit은 전달 직전에 아래 명령으로 확인하여 전달 메시지의
`Latest Commit SHA`에 기록합니다.

```bash
git fetch origin
git rev-parse origin/develop
```

## 2. 전달 범위

| 영역 | 주요 경로 | 내용 |
|---|---|---|
| 프로젝트 설정 | `config/`, `manage.py` | 설정 분리, URL, 로깅, PostgreSQL 연결 |
| 인증·사용자 | `apps/accounts/` | 독립 세션 매핑, OTP, DEBUG 테스트 로그인, 사용자 검색 |
| 부모 연동 | `apps/integration/` | 두 PostgreSQL VIEW의 읽기 전용 조회와 Context resolver |
| PRD | `apps/prds/` | PRD, 템플릿, 참여자, 질문·답변, 코멘트, 상태·휴지통·기여도 |
| 브레인스토밍 | `apps/brainstorm/` | React CDN 캔버스, 보드 버전, 메모·연결선·협업 충돌 |
| AI | `apps/ai/` | Gemini adapter, 프롬프트, 작업·사용 로그, 코치·진단·PRD 반영 |
| 운영 작업 | `apps/jobs/` | AI worker와 자정 유지보수 command |
| 공통 | `apps/common/` | 오류 응답, health check, Slack adapter, 공통 화면 routing |
| 화면 | `templates/`, `static/` | Bootstrap 화면과 브레인스토밍 React CDN 정적 앱 |
| 검증 | `tests/` | 단위·API·권한·동시성·PostgreSQL 회귀 테스트 |

로컬 PPT, 캡처, `.env`, DB dump와 내부 팀 협업 문서는 전달하지 않습니다.

## 3. 데이터베이스와 migration

현재 migration head는 다음과 같습니다.

| 앱 | migration head | 비고 |
|---|---|---|
| accounts | `0001_initial` | Django session용 최소 외부 사용자 매핑 |
| integration | `0001_initial` | unmanaged VIEW 모델 상태만 관리하며 VIEW DDL 없음 |
| prds | `0015_apply_final_prd_template_questions` | 최종 템플릿과 기존 PRD 질문 갱신 포함 |
| brainstorm | `0008_canvas_order_and_soft_delete` | 다중 보드 정렬·최신 지정·소프트 삭제 |
| ai | `0029_seed_prd_evaluation_synthesis_prompt` | 관점별 진단과 종합 진단 프롬프트 포함 |

최종 PRD 템플릿은 유형별로 다음 문항을 생성합니다.

- 신규 프로젝트: 30문항
- 기존 프로젝트 신규 기능: 32문항
- 기존 기능 개선: 32문항

`prds.0014`, `prds.0015`는 기존 PRD 질문도 갱신합니다. 부모 통합 DB에 실제 사용자 작성
데이터가 존재한다면 적용 전에 staging 백업과 결과 검토가 필요합니다. 현재 독립 개발 DB의
기존 PRD는 데모 데이터이므로 갱신을 허용했습니다.

적용 명령:

```bash
python manage.py migrate
python manage.py makemigrations --check --dry-run
```

## 4. Python requirements

기본 패키지는 다음과 같습니다.

```text
Django==5.2.6
jsonschema==4.26.0
psycopg[binary]==3.2.10
python-dotenv==1.1.1
```

개발 환경은 `coverage==7.10.6`, `ruff==0.12.12`, 운영 환경은 `gunicorn==23.0.0`을 추가합니다.
React와 ReactDOM은 Python 패키지가 아니며 브레인스토밍 화면에서 고정 버전 CDN으로만
불러옵니다. Tailwind runtime과 브라우저용 Babel은 사용하지 않습니다.

## 5. 필요한 환경변수

실제 값은 비밀 저장소로 전달하고 아래 이름과 용도만 공유합니다.

| 분류 | 환경변수 |
|---|---|
| Django | `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_SITE_URL`, `DJANGO_TIME_ZONE` |
| 자식 DB | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_OPTIONS` |
| 부모 VIEW DB | `INTEGRATION_DB_NAME`, `INTEGRATION_DB_USER`, `INTEGRATION_DB_PASSWORD`, `INTEGRATION_DB_HOST`, `INTEGRATION_DB_PORT`, `INTEGRATION_DB_OPTIONS` |
| 부모 Context | `INTEGRATION_ACTIVE_ROUND_STATUSES`, `INTEGRATION_APPROVED_USER_STATUS`, `INTEGRATION_CONTEXT_RESOLVER_CLASS` |
| AI | `AI_PROVIDER_CLASS`, `GEMINI_API_KEY`, `AI_JOB_TIMEOUT_SECONDS`, `AI_JOB_MAX_ATTEMPTS`, AI 사용량·입력 제한 변수 |
| 페이지네이션 | `HOME_PAGE_SIZE`, `HOME_MAX_PAGE_SIZE`, `PRD_DETAIL_PAGE_SIZE`, `PRD_DETAIL_MAX_PAGE_SIZE`, 사용자 검색 page size 변수 |
| 협업 | `POLLING_INTERVAL_MS`, `POLLING_MIN_INTERVAL_MS`, `POLLING_MAX_INTERVAL_MS` |
| Slack | `SLACK_DELIVERY_MAX_ATTEMPTS`, `SLACK_DELIVERY_RETRY_BASE_SECONDS` |
| 보관 | `PRD_TRASH_RETENTION_DAYS`, `BRAINSTORM_DELETE_RETENTION_DAYS`, AI preview·chat retention 변수 |

전체 목록과 안전한 예시는 `.env.example`을 기준으로 합니다. `DJANGO_SITE_URL`은 Slack 초대
메시지의 PRD 바로가기 URL 생성에도 사용하므로 반드시 실제 서비스 origin으로 지정합니다.

## 6. 외부 연동 계약

### PostgreSQL VIEW

- `public.ax_user_team_login_view`
- `public.user_round_team_view`
- `managed=False`, 조회 전용이며 자식 migration에서 VIEW를 만들거나 수정하지 않음
- 부모 원본 `accounts_user`, `rounds_*`, `teams_*` 테이블을 직접 JOIN하지 않음
- 회차 팀은 `user_id + round_id`로 재검증하고 대표 팀 값을 현재 회차 팀으로 간주하지 않음
- 장애 또는 모호한 복수 팀 결과에서는 쓰기 권한을 허용하지 않음

### Slack

- 부모의 `notifications.slack.send_slack_dm_ax()`와 `send_slack_dm_ax_batch()`만 호출
- 전달 ID는 부모 `accounts_user.id`와 같은 외부 `user_id`
- 참여자 추가 알림에는 PRD 바로가기 URL을 본문과 URL 인자에 모두 전달
- 코멘트 알림은 작성자를 제외한 대상 참여자에게 전달
- DB commit 후 호출하고 최대 3회 재시도하며 최종 실패가 도메인 저장을 롤백하지 않음

### Gemini

- `GEMINI_API_KEY`는 코드나 DB seed에 저장하지 않음
- 웹 요청은 PostgreSQL 작업 테이블에 job을 만들고 별도 worker가 실제 모델을 호출
- AI 출력의 PRD·질문·메모·섹션 ID와 version을 서버 데이터로 다시 검증
- 개발용 샘플 진단 캐시는 운영 설정에서 사용하지 않음

## 7. 별도 프로세스와 스케줄

웹 프로세스 외에 AI worker를 실행합니다.

```bash
python manage.py run_job_worker
```

매일 서비스 timezone 기준 자정에 다음 command를 한 번 실행합니다.

```bash
python manage.py run_midnight_maintenance
```

이 command는 기한이 지난 PRD의 상태 완료 처리, 30일이 지난 PRD·브레인스토밍 소프트 삭제
데이터의 영구 삭제와 만료된 AI 임시 데이터를 정리합니다. 반복 실행해도 안전하게 동작하도록
구현되어 있습니다.

## 8. 주요 최신 정책

- 회차 없는 개인 PRD와 일반 팀 PRD를 허용합니다.
- 과거 회차 PRD도 명시적 참여자라면 조회할 수 있습니다.
- PRD 상태와 답변·참여자·코멘트는 version 충돌 시 `409 Conflict`를 반환합니다.
- 브레인스토밍은 여러 보드 버전을 가지며 지정된 최신 보드만 편집할 수 있습니다.
- 이전 보드 메모 lineage는 기여도 계산에서 아이디어 발전 이력을 보존하는 데 사용합니다.
- 질문 보류는 진행률과 AI 진단 입력에서 제외합니다.
- AI 진단 한 번으로 PM·엔지니어링·투자자 관점과 종합 결과를 생성합니다.
- 기여도 결과는 관리자만 조회하며 최종 점수는 코멘트 50%, 메모 50%의 100점 기준입니다.
- PRD 삭제는 30일 소프트 삭제이며 휴지통의 삭제 완료 요청도 보관기한을 앞당기지 않습니다.

## 9. 검증 명령과 현재 결과

```bash
python manage.py check --settings=config.settings.test
python manage.py makemigrations --check --dry-run --settings=config.settings.test
python manage.py test --settings=config.settings.test
python manage.py test --settings=config.settings.test_postgres
python -m ruff format --check .
python -m ruff check .
```

2026-09-09 기준 로컬 SQLite에서는 398개 중 PostgreSQL 전용 5개를 제외한 393개가 통과했습니다.
GitHub Actions run `34329903572`의 PostgreSQL 16 환경에서는 398개 전체와 migration 검사,
Ruff가 통과했고 애플리케이션 커버리지는 88%였습니다. 운영 `check --deploy`도 성공했지만,
HSTS include-subdomains·preload 권고 2건은 부모 서비스의 전체 HTTPS 범위를 확인한 뒤 결정해야
합니다. 현재 로컬 PostgreSQL
재실행은 DB 계정에 테스트 DB 생성 권한이 없어 시작 전에 중단되었으며, 코드 실패로 기록하지
않습니다. 부모 통합 환경에서도 운영 DB가 아닌 분리된 테스트 DB와 `CREATE DATABASE` 권한으로
다시 실행합니다.

## 10. 미구현·부모팀 결정 필요 사항

- 기여도 결과를 부모 점수 모델로 전달하는 payload·인증·idempotency 규격
- 부모의 `results_scoreinput` 사용 여부
- 부모 공통 감사 로그에 남길 범위와 보존 책임
- 독립 OTP를 부모 `request.user` 인증으로 교체하는 최종 연결부
- 부모 base template, URL namespace와 CSP에 정적 자산·React CDN origin을 합치는 방식
- 브레인스토밍 AI 분석·AI 항목 분류 Legacy API의 통합 대상 제외 여부

Redis, Celery, Django Channels는 현재 필수 의존성이 아니며 통합 과정에서 임의로 추가하지
않습니다.
