# 2026-09-06 develop 동기화 기록

## 1. 기준점

| 항목 | 값 |
|---|---|
| 동기화 전 commit | `935d35e` |
| 동기화 후 commit | `f77bb29` |
| 반영 브랜치 | `develop` → `heeju` fast-forward |
| 충돌 | 없음 |
| migration | `ai.0021`, `ai.0022` 추가 |
| requirements·환경변수 | 변경 없음 |

이 문서는 해당 구간의 커밋 메시지만 옮긴 변경 이력이 아니라, 최종 코드에서 실제로 유지되는
동작을 기준으로 작성한다. 병합 과정에서 추가됐다가 되돌려진 질문별 버튼 등의 중간 상태는 현재
기능으로 기록하지 않는다.

## 2. 관점별 PRD 전체 초안

PM, 엔지니어링, 투자자 중 현재 선택한 관점으로 PRD 전체 질문의 답변 초안을 생성하는 기능이
추가됐다. 기존 `AI 진단하기`는 세 관점을 한 번에 평가하고, 새 `AI 초안 작성`은 선택한 한 관점의
초안을 만드는 서로 다른 기능이다.

처리 흐름은 다음과 같다.

1. 로그인·PRD 접근·AI 요청 권한과 persona를 서버에서 검증한다.
2. 현재 PRD 제목, 소개, 섹션, 활성 질문, 기존 답변과 질문 version snapshot을 구성한다.
3. `PRD_PERSPECTIVE_DRAFT/perspective_draft` job을 PostgreSQL 작업 테이블에 멱등 등록한다.
4. worker가 구조화 JSON을 생성하고 모든 현재 질문 ID가 정확히 한 번씩 포함됐는지 검증한다.
5. 화면은 질문별 초안과 이유를 미리보기로 보여주며 사용자가 반영 항목을 선택한다.
6. 반영 시 job 소유권·권한·성공 상태와 질문 version을 재검증하고 승인 항목만 저장한다.

현재 PRD version과 일치하는 같은 사용자·관점의 최신 진단 결과가 있으면 초안의 참고자료로
사용한다. 진단 결과가 없거나 오래됐거나 실패해도 초안 요청 자체를 막지 않는다. 전체 PRD를
대상으로 하므로 job timeout은 100초다.

미리보기의 `AI 채팅으로 가기`는 질문이 속한 섹션의 코치 대화를 열고 질문과 초안을 입력란에
채운다. 버튼만 누른 상태에서는 메시지와 답변을 저장하지 않으며 사용자가 직접 전송해야 한다.

## 3. 데이터와 API 변경

`0021_perspective_draft_feature_type`은 AI prompt, job, usage log에
`PRD_PERSPECTIVE_DRAFT`와 `perspective_draft` 조합을 허용하도록 choice와 DB check constraint를
갱신한다. `0022_seed_prd_perspective_draft_prompt`는 v1 system instruction과 JSON schema를
데이터 migration으로 등록한다. 기존 행을 삭제하거나 덮어쓰지 않는다.

추가 API는 다음과 같다.

- `POST .../ai/perspective-draft/run/`: 선택 관점 job 생성
- `POST .../ai/perspective-draft/<job_id>/apply/`: 질문별 선택 승인 반영
- 상태 조회, 취소, 재시도는 기존 공통 AI job API 사용

## 4. AI 코치 연결 개선

- AI 진단의 섹션 결과에서 해당 섹션 AI 코치 상담으로 이동할 수 있다.
- 관점별 초안에서도 질문·초안을 해당 섹션 코치 입력란에 전달할 수 있다.
- 정상 처리 중인 코치 메시지에는 실패용 재시도 버튼을 표시하지 않는다.
- 진단 취소 버튼의 화면 스타일을 기존 작성 화면과 맞췄다.

## 5. 브레인스토밍 연결선 표시 개선

- 연결선 경로 후보를 늘려 메모·섹션 이름표와 겹치는 경우를 줄였다.
- 계산된 경로를 캔버스 표시 영역 밖으로 내보내지 않도록 제한했다.
- 선택·강조된 연결선이 항목 이름표를 덮지 않도록 레이어 순서를 조정했다.

이는 시각적 경로 계산 변경이며 연결선 UUID, 중복·자기 연결 금지, version, idempotency와 같은
서버 데이터 계약은 변경하지 않는다.

## 6. 구조화 로그 개선

JSON formatter가 request ID뿐 아니라 호출부가 `extra`로 넘긴 job ID, error code, 시도 횟수 등
운영 진단 필드를 보존한다. 예외 stack도 유지하며 JSON으로 직렬화할 수 없는 값은 문자열로
변환해 로그 전체가 사라지지 않게 한다. AI worker는 잘못된 모델 출력 전문을 무제한 기록하지
않고 최대 2,000자까지만 남긴다.

## 7. 예외·권한·무결성

- 지원하지 않는 persona, 활성 질문 없음, 빈·누락·중복·외부 질문 ID는 저장 전에 거절한다.
- 요청 사용자 소유가 아닌 job이나 다른 PRD job을 조회·반영할 수 없다.
- AI 요청과 반영 권한을 별도로 검사하며 completed 잠금 정책을 그대로 적용한다.
- 미리보기 이후 질문 version이 바뀌면 409로 중단한다.
- AI 결과는 사용자 승인 전 기존 답변을 변경하지 않는다.

## 8. 검증 상태와 후속 작업

- `tests/test_logging.py`가 기본 JSON 필드, request ID, `extra`, 예외와 비직렬화 값 처리를 검증한다.
- `tests/test_ai_infrastructure.py`가 AI 실패 로그의 진단 필드 보존을 보강한다.
- 기존 템플릿 계약 테스트는 최종 화면 구성에 맞게 갱신됐다.
- `tests/test_ai_perspective_draft.py`가 persona, 멱등성, 100초 timeout 전달, 출력 ID 검증,
  승인 전 미저장, 부분 승인, job 소유권, version 충돌, 활성 질문 없음, 권한·완료 잠금, 중복
  반영, batch rollback과 인증·부모 연동 장애의 JSON 응답을 검증한다. 가짜 provider를 사용하므로
  테스트 중 Gemini API 호출과 토큰 소비는 없다.

배포 전에는 `python manage.py migrate`로 두 migration을 적용하고 AI worker가 동일한 최신 코드를
사용하는지 확인한다. 추가 환경변수는 없으며 기존 Gemini provider 설정을 사용한다.
