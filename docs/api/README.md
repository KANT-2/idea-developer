# API 계약 개요

이 문서는 현재 외부 HTTP 경로의 범위와 공통 규칙을 요약한다. 세부 request·response 필드는
각 Django view, serializer 역할의 검증 함수와 자동 테스트를 최종 근거로 사용한다. 모든 제품
API는 `/api/v1/` 아래에 있으며 헬스체크를 제외하고 Django session 로그인이 필요하다.

## 공통 규칙

- 쓰기 요청은 CSRF 토큰과 서버 권한 검사를 모두 통과해야 한다.
- PRD 하위 API는 URL의 ID만 신뢰하지 않고 PRD 참여 역할을 다시 확인한다.
- 회차 팀 작업은 `IntegrationContext`와 부모 VIEW의 `user_id + round_id` 참가정보를 검증한다.
- 수정 요청은 해당 resource의 `version`을 포함하고 충돌 시 `409 Conflict`와 최신 데이터를 받는다.
- 중복 생성 위험이 있는 요청은 `Idempotency-Key`를 사용한다.
- 목록 API는 서버 페이지네이션과 최대 페이지 크기를 적용한다.
- 오류는 공통 JSON envelope의 오류 코드·메시지·필드 오류·request ID를 사용한다.

상태 코드별 의미와 인증, 동시 수정, 외부 연동, AI 및 삭제 예외의 화면 처리 원칙은
[`EXCEPTION_CATALOG.md`](../EXCEPTION_CATALOG.md)를 따른다. 사용자 기능에서 어떤 API가 필요한지는
[`FUNCTIONAL_SPEC.md`](../FUNCTIONAL_SPEC.md)를 함께 확인한다.

## 주요 경로

| 영역 | 기준 경로 | 설명 |
|---|---|---|
| 헬스체크 | `/api/v1/health/` | 인증 없는 배포 상태 확인 |
| 인증 | `/api/v1/auth/` | OTP 요청·검증 |
| 사용자 | `/api/v1/users/` | 권한 범위 내 사용자 검색 |
| 홈 | `/api/v1/home/` | KPI, PRD 목록, 튜터 학생 검색, 최근 활동 |
| PRD | `/api/v1/prds/` | 생성, 상세, 답변, 참여자, 코멘트, 상태, 휴지통 |
| PRD AI | `/api/v1/prds/<prd_id>/ai/` | 코치, 3관점 진단·종합, 질문 초안, 세 관점 통합 전체 초안, 작업 상태·취소·재시도 |
| 브레인스토밍 | `/api/v1/prds/<prd_id>/brainstorm/` | 보드, 노드, 연결선, viewport, polling, PRD 반영 |

### 브레인스토밍 보드 버전

| Method·경로 | 주요 입력 | 결과·검증 |
|---|---|---|
| `GET /canvas/` | 선택 시 `X-Brainstorm-Canvas-Id` 또는 `canvas_id` | 선택 보드 전체 상태와 활성 버전 목록을 반환한다. 미지정 시 `display_order` 첫 최신 보드를 연다. |
| `GET /boards/` | 없음 | 삭제되지 않은 보드를 최신 순서대로 반환한다. |
| `POST /boards/` | `source_canvas_id`, `Idempotency-Key` | 선택 보드를 복제하고 새 보드를 최신 순서 맨 앞에 둔다. |
| `PATCH /boards/order/` | `canvas_ids`: 활성 보드 ID 전체 | 정확한 ID 집합을 검증하고 첫 ID를 최신으로 지정한다. 부분 목록·중복·타 PRD ID는 거절한다. |
| `DELETE /boards/<canvas_id>/` | 최신 보드 ID | 최신 보드를 소프트 삭제하고 다음 보드를 승격한다. 이전 보드와 마지막 활성 보드는 삭제할 수 없다. |

노드·연결선·자동 정렬·AI PRD 반영 mutation은 선택한 캔버스가 현재 최신인지 서버에서 다시
검증한다. 순서 변경과 삭제는 모든 활성 보드에 change event를 남겨 polling 중인 화면이 최신
지정을 다시 읽게 한다.

## 공개 범위가 제한된 API

- 기여도 결과와 동일 입력 재평가는 staff/superuser 관리자만 사용할 수 있다.
- AI 사용 기록과 PRD 수정 이력은 현재 사용자 화면에서 제공하지 않는다.
- 브레인스토밍 AI 분석·항목 분류 API는 Legacy 호환 계약이며 신규 UI에서 사용하지 않는다.
- 브레인스토밍 Markdown 내보내기 API는 제거됐다. PRD Markdown 내보내기는 유지한다.
- `DEBUG=true`에서만 개발 전용 로그인 URL을 등록한다.

URL의 단일 기준은 `config/urls.py`와 각 앱의 `*_urls.py`이다. 경로를 변경하면 이 문서와 관련
테스트를 같은 PR에서 갱신한다.

## PRD 진단 종합과 세 관점 통합 전체 초안

| 단계 | Method·경로 | 주요 입력 | 결과·검증 |
|---|---|---|---|
| 진단 조회 | `GET /api/v1/prds/<prd_id>/ai/evaluation/` | 없음 | 세 관점별 최신 job과 현재 여부, 종합 job과 현재 여부를 함께 반환한다. |
| 종합 요청 | `POST /api/v1/prds/<prd_id>/ai/evaluation/synthesis/run/` | `Idempotency-Key` | 최신 상태로 성공한 세 관점 진단을 검증하고 종합 job을 생성한다. |
| 초안 생성 | `POST /api/v1/prds/<prd_id>/ai/perspective-draft/run/` | `Idempotency-Key` | 세 관점과 현재 PRD context를 입력으로 job을 생성한다. 신규 job은 202, 같은 멱등 요청은 기존 job과 200을 반환한다. |
| 상태 조회 | `GET /api/v1/prds/<prd_id>/ai/jobs/<job_id>/` | URL의 job ID | 요청 사용자 소유의 같은 PRD job만 조회한다. |
| 취소·재시도 | 공통 `jobs/<job_id>/cancel/`, `retry/` | job ID | 공통 AI 상태 전이 규칙을 따른다. |
| 선택 반영 | `POST /api/v1/prds/<prd_id>/ai/perspective-draft/<job_id>/apply/` | `approved_questions: [{question_id, version}]` | 성공한 본인 job의 미리보기 항목만 허용하고 질문 version이 바뀌면 409를 반환한다. |

종합 결과의 섹션 ID는 현재 진단 입력과 정확히 일치해야 하며, 중복·누락·잘못된 상태값은 폐기한다.
초안 생성 결과의 `answers`에는 `question_id`, 생성 당시 `question_version`, 정화된 `draft`, 정화된
`reasoning`이 포함된다. 반영할 질문은 하나 이상이어야 하며 중복 ID는 허용하지 않는다.
