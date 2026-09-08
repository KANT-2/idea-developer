# 테스트·보안·운영 품질 기준

## 1. 자동 검증

```powershell
python manage.py check --settings=config.settings.test
python manage.py makemigrations --check --dry-run --settings=config.settings.test
python manage.py test --settings=config.settings.test
ruff format --check .
ruff check .
```

Pull Request와 `develop`, `main` push에서는 GitHub Actions가 PostgreSQL 16으로 전체 테스트를
실행한다. 애플리케이션 코드 커버리지는 85% 미만이면 실패하며 운영 설정의 `check --deploy`도
통과해야 한다.

2026-09-07 최신 `develop` 병합 후 로컬 회귀 기준으로 391개 테스트를 발견해 386개가 통과했고,
SQLite에서 지원하지 않는 PostgreSQL 행 잠금 전용 테스트 5개는 건너뛰었다. `apps` 기준 측정
커버리지는 88.1%다. 건너뛴
5개는 PostgreSQL 16 CI 또는 테스트 DB 생성 권한이 있는 로컬 PostgreSQL에서 실행한다.

## 2. 테스트 범위

| 영역 | 주요 검증 |
|---|---|
| 인증 | 정상·미등록 동일 응답, 비활성·미승인, 만료·재사용·실패 횟수, rate limit, session, open redirect |
| 부모 연동 | unmanaged·쓰기 차단, `user_id + round_id`, 복수 팀·VIEW 장애 fail closed, fixture resolver |
| PRD | 유형·상태·외부 ID, 템플릿 복제, completion rate, idempotency, DB constraint |
| 홈 | 접근 범위, KPI, 과거·회차 없는 PRD, 필터·정렬·날짜 경계, N+1 방지 |
| 상세 편집 | 역할 권한, 답변·참여자·코멘트 version 충돌, 완료 잠금, 재개 감사 |
| 브레인스토밍 | 이동·보류·삭제·복원, 연결 무결성, 최신 보드 단독 편집, 순서 변경·최신 승격, polling cursor, batch rollback |
| AI | schema·ID 검증, prompt 분리, timeout·취소·재시도, 사용량, 코치 동시 append, 3관점 진단·종합, 승인 전 미저장, 통합 전체 초안의 선택 반영·version 충돌 |
| 로깅 | request ID·`extra` 필드 보존, 예외 stack, 직렬화 불가능한 값의 안전한 문자열 변환 |
| 기여도 | lineage 중복 제거, 내용 편집자, PRD 반영 confidence, 50:50 정규화, AI 실패 유지 |
| 유지보수 | 마감 자동 완료, 30일 TTL, 빈 batch idempotency, 삭제 감사 보존 |
| 알림 | transaction commit 이후 호출, 수신자 제외, 일시 실패 재시도, 최종 실패 시 저장 유지 |
| 화면 전환 | 루트·로그인 `next`, 홈→생성→상세, 상세↔브레인스토밍, 개발 모드 404 복구, API 비정상 응답 유지 |

## 3. 보안 통제

- 헬스체크 외 제품 API는 Django session 인증이 필요하다.
- 상태 변경 요청은 CSRF를 검사하고 내부 `next` URL만 허용한다.
- 모든 PRD 하위 API는 서버에서 참여 역할과 완료 잠금을 다시 확인한다.
- 부모 VIEW connection은 `default_transaction_read_only=on`이며 ORM write와 migration routing을
  차단한다.
- OTP 원문, DB 비밀번호와 API 키를 저장소·로그에 남기지 않는다.
- AI system instruction과 신뢰하지 않는 사용자 데이터를 분리하고 출력 schema·ID를 재검증한다.
- 사용자 입력은 plain text로 저장하고 출력 시 escape·Markdown sanitize를 수행한다.
- 검색어·메시지·AI context·페이지 크기·좌표·확대 비율에 상한을 둔다.
- 운영 환경은 HTTPS redirect, secure cookie, HSTS, allowed hosts와 SMTP backend를 배포 검사한다.

## 4. 배포 전 체크리스트

1. 전체 PostgreSQL CI와 migration graph가 통과했는지 확인한다.
2. DB를 백업하고 migration 역방향 적용 가능성을 확인한다.
3. `.env` 대신 배포 비밀 저장소에서 secret을 주입한다.
4. `collectstatic`, 웹 프로세스, AI worker와 자정 유지보수 작업을 각각 구성한다.
5. 부모 VIEW 계정이 읽기 전용이고 실제 상태값 설정이 일치하는지 확인한다.
6. 부모 Slack 모듈과 CSP의 React CDN origin을 확인한다.
7. 배포 후 health, 로그인, PRD 조회·저장, worker 작업 하나를 smoke test한다.

## 5. 의도적으로 남은 통합 결정

- 부모 기여도 전달 API·payload·멱등성 계약
- `results_scoreinput` 사용 여부
- 부모 공통 감사 로그의 책임과 보존기간
- Legacy 브레인스토밍 AI API의 기존 호출자 확인 후 제거 시점

## 6. 최신 통합 기능의 검증 근거

- 세 관점 통합 PRD 전체 초안은 `tests/test_ai_perspective_draft.py`에서 세 persona 입력, 멱등 요청,
  60초 timeout 전달, 승인 전 미저장, 부분 승인, 다른 사용자 job 차단, 질문 version 409, 결과
  질문 ID 누락·중복·범위 이탈, 활성 질문 없음, viewer·완료 잠금, 중복 반영과 batch rollback을
  검증한다. 비로그인과 부모 연동 장애도 HTML 오류 화면이 아닌 401·503 JSON인지 확인한다.
  테스트 provider만 사용하므로 Gemini API를 호출하거나 토큰을 소비하지 않는다.
- 진단 종합은 `tests/test_ai_prd_evaluation.py`에서 세 관점 완료 전 요청 거절, 멱등 job 생성,
  worker 결과 처리, 최신 종합 결과 복원을 검증한다.
- 구조화 로그의 `extra` 보존과 직렬화 실패 방지는 `tests/test_logging.py`에서 검증한다.
- `tests/test_ui_navigation.py`는 로그인 전후 진입 경로, 보호 화면의 안전한 `next`, 홈·새 PRD
  렌더링, 일반 화면 HTML 404/API JSON 404 분리, `DEBUG=True` 기술 404 차단, 모든 주요 fetch
  client의 비정상 응답·네트워크 실패 방어를 검증한다. 브라우저 smoke test는 홈→새 PRD 2단계와
  참여자 검색, 홈→PRD 상세, 상세→같은 탭 브레인스토밍→상세 복귀, 404→홈 복귀를 확인한다.
- SQLite 전체 회귀에서는 PostgreSQL `select_for_update` 전용 동시성 테스트 5개가 skip된다.
  GitHub Actions의 PostgreSQL 16 job에서 이 5개를 포함해 실행한다. 로컬 PostgreSQL에서 직접
  실행하려면 애플리케이션 DB와 분리된 테스트 DB 생성 권한이 필요하다.
