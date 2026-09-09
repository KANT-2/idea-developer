# 데이터 사전

> 기준: Django 모델 및 migration, 2026-09-09

## 1. 인증·외부 연동

| 테이블 또는 VIEW | 소유 | 목적 | 핵심 키·제약 |
|---|---|---|---|
| `idea_local_user_mapping` | 자식 | Django session용 최소 사용자 매핑 | `external_user_id` unique, usable password 금지 |
| `idea_login_otp_challenge` | 자식 | OTP 해시·만료·사용·실패 횟수 | UUID PK, 실패 횟수 5 이하, 이메일·IP 시간 인덱스 |
| `idea_login_audit_log` | 자식 | 로그인 성공·실패·로그아웃 감사 | 외부 user ID·발생 시각 인덱스, 원문 OTP 미저장 |
| `public.ax_user_team_login_view` | 부모 | 사용자 표시·활성·승인·역할 조회 | `managed=False`, 읽기 전용, `user_id` 식별 |
| `public.user_round_team_view` | 부모 | 회차별 참가자·팀 조회 | `managed=False`, 읽기 전용, `user_id + round_id` 검증 |

## 2. PRD

| 테이블 | 목적 | 핵심 관계·무결성 |
|---|---|---|
| `prd_templates` | 세 PRD 유형별 템플릿 | `prd_type` unique 및 허용값 check |
| `prd_template_sections` | 템플릿 섹션 | template FK, `(template, position)` unique |
| `prd_template_questions` | 템플릿 질문 | section FK, `(section, position)` unique |
| `prds` | PRD aggregate root | nullable `round_id/team_id`, status/type/version check, 회차별·회차 없는 idempotency unique, 삭제 필드 일관성 |
| `prd_participants` | 사용자별 PRD 역할 | `(prd, user_id)` unique, 외부 participant 중복 방지, role/version check |
| `prd_sections` | 생성된 PRD 섹션 | PRD FK, `(prd, position)` unique, 소프트 삭제 일관성 |
| `prd_questions` | 섹션 질문과 완료·보류 | section FK, `(section, position)` unique, version 양수, 완료도 복합 인덱스 |
| `prd_answers` | 질문별 단일 답변 | question OneToOne, 변경 사용자 외부 ID |
| `prd_comments` | 전체·질문별 코멘트 | PRD FK, question `SET_NULL`, 역할·유형·version·소프트 삭제 check |
| `prd_change_history` | 사용자에게 필요한 도메인 변경 이력 | PRD FK, before/after JSON, 최신순 인덱스 |
| `prd_status_audit_logs` | 완료·재개 감사 | PRD FK, actor/action check, 이전 완료 시각 보존 |
| `prd_deletion_audit_logs` | 영구 삭제 후 최소 사실 기록 | PRD FK 없음, 삭제 PRD·제목·행위자 snapshot |

PRD 상태는 `in_progress`, `completed`, `held`, `dropped` 하나만 사용한다. 회차 없는 PRD는
`round_id=null`, `team_id=null`이며 명시적 참여 관계로 접근을 제어한다. 보류 질문은 완성도와 AI
충족도 입력에서 제외한다.

## 3. 브레인스토밍

| 테이블 | 목적 | 핵심 관계·무결성 |
|---|---|---|
| `brainstorm_canvases` | PRD의 버전별 보드 | `(prd, version_number)` unique, source self FK, 생성 idempotency unique, `display_order`, `is_deleted/deleted_at` 일관성 |
| `brainstorm_nodes` | note/title 노드 | UUID PK, lineage 인덱스, 상태·유형 필드 조합 check, version, 소프트 삭제, 생성 idempotency unique |
| `brainstorm_connections` | 두 노드의 무방향 연결 | UUID PK, 자기 연결 금지, node pair·idempotency unique, version·소프트 삭제 |
| `brainstorm_user_viewports` | 사용자별 pan·zoom | `(canvas, user_id)` unique, zoom 0.30~2.00 check |
| `brainstorm_change_logs` | polling·작업 단위 변경 스트림 | 증가 PK cursor, `operation_id`, canvas 최신순 인덱스 |
| `brainstorm_audit_logs` | 보류 연결선 삭제 등 보안·감사 기록 | actor·target check, reason·생성 시각 인덱스 |

일반 note는 미분류일 때 `default`, 섹션에 배치되면 `accepted`, 보류 영역에서는 `held`다. held
노드는 반드시 `section_id=null`이고 연결선은 영구 삭제한다. `held_from_section_id`는 보류 직전
섹션을 임시로 기억하며 보류 해제 시 그 섹션이 유효하면 돌아간다. 버전 보드 복제 시 노드 PK는
새로 만들지만 `lineage_id`는 유지한다. 활성 캔버스는 `display_order`, 버전 역순, ID 역순으로
정렬하고 첫 행만 최신·편집 가능하다.

## 4. AI·작업·기여도

| 테이블 | 목적 | 핵심 관계·무결성 |
|---|---|---|
| `ai_prompts` | 기능별 versioned system prompt와 JSON schema | `(feature_type, version)` unique, 기능별 활성 prompt 하나 |
| `ai_jobs` | PostgreSQL 비동기 작업 큐 | prompt `PROTECT`, 요청 idempotency unique, 상태·시도·timeout check, claim·lease 인덱스 |
| `ai_usage_logs` | 실행별 토큰·비용·성공·실패 기록 | job `SET_NULL`, PRD FK, feature/action 조합 및 토큰 합계 check |
| `ai_coach_conversations` | PRD·섹션·사용자별 코치 대화 | section scope와 whole-PRD scope unique, 만료 인덱스 |
| `ai_coach_messages` | 순서가 있는 대화 메시지 | `(conversation, sequence)` unique, plain text 저장, job `SET_NULL` |
| `ai_prd_apply_records` | 승인된 AI PRD 반영 작업 | preview job OneToOne `PROTECT`, 요청 unique, section/whole scope check |
| `ai_prd_apply_items` | 질문별 이전·통합 답변과 근거 노드 | `(record, question)` unique, question `PROTECT`, confidence 범위 check |
| `contribution_evaluations` | 완료 시점별 기여도 계산 snapshot | completion audit OneToOne `PROTECT`, `(prd, calculation_version)` unique, input fingerprint |
| `contribution_user_scores` | 참여자별 메모·코멘트·총점 | `(evaluation, user_id)` unique, 각 정규화 점수 0~100 |
| `contribution_comment_scores` | 코멘트별 AI 반영 근거 | `(evaluation, comment)` unique, comment `PROTECT`, score/confidence 범위 |

`AI_Usage_Log`만 실제 사용 횟수와 비용 집계에 사용하고 prompt 정의는 집계하지 않는다. AI
출력의 node·section·question ID는 저장 전 현재 DB와 다시 대조한다.

## 5. 기여도 계산 필드

```text
memo_raw = sum(사용자가 기여한 실제 반영 lineage별 confidence)
memo_contribution = memo_raw / 전체 참여자 memo_raw 합 * 100

comment_raw = sum(기여 가능한 코멘트의 reflection_score)
comment_contribution = comment_raw / 전체 참여자 comment_raw 합 * 100

total_score = 0.5 * memo_contribution + 0.5 * comment_contribution
```

동일 lineage의 최초 작성자와 의미 있는 내용 편집자에게 각각 기여를 인정한다. 담당자·좌표·섹션·
상태만 바꾼 행위는 새 내용 기여가 아니다. tutor 리뷰와 `is_contribution_eligible=false` 코멘트는
계산에서 제외한다.

## 6. 보존·정리

| 데이터 | 보존 정책 |
|---|---|
| 소프트 삭제 PRD | 30일 복구 가능, 이후 자정 유지보수에서 영구 삭제 |
| 소프트 삭제 노드·연결선 | 30일 후 batch 영구 삭제 |
| PRD 삭제 사실 로그 | PRD FK 없이 장기 보존 |
| AI 임시 preview payload | 기본 7일 후 output payload 정리 |
| AI 코치 대화 | 마지막 활동 후 30일 TTL |
| terminal AI 작업·사용 로그 | 자동 재대기열 등록 없이 실행 근거 보존 |

보존일과 batch 크기는 환경변수로 조정하며, 영구 삭제는 migration이 아니라 management command
서비스가 수행한다.
