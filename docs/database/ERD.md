# Idea Developer ERD

> 기준: Django 모델 및 migration, 2026-09-07

## 1. 시스템 경계

부모 시스템은 사용자·회차·팀 원장을 소유하고, Idea Developer는 PRD·브레인스토밍·AI 결과를
소유한다. 두 영역은 물리 FK가 아닌 외부 식별자와 읽기 전용 VIEW 계약으로 연결한다.

```mermaid
flowchart LR
    subgraph Parent[부모 PostgreSQL · public schema]
        U[ax_user_team_login_view<br/>managed=False]
        RT[user_round_team_view<br/>managed=False]
    end

    subgraph Child[Idea Developer · idea_developer schema]
        LU[idea_local_user_mapping]
        P[prds]
        PP[prd_participants]
        B[brainstorm_canvases]
        AI[ai_jobs / ai_usage_logs]
    end

    U -. external_user_id .-> LU
    U -. user_id 검증 .-> P
    U -. user_id 검증 .-> PP
    RT -. user_id + round_id + team_id 검증 .-> P
    P --> PP
    P --> B
    P --> AI
```

부모 VIEW에는 `INSERT`, `UPDATE`, `DELETE`를 실행하지 않는다. `creator_user_id`, `user_id`,
`author_user_id`, `actor_user_id`, `round_id`, `participant_id`, `team_id`는 부모 원장의 외부 ID다.

## 2. 인증·연동

```mermaid
erDiagram
    IDEA_LOCAL_USER_MAPPING {
        bigint id PK
        bigint external_user_id UK
        varchar email_snapshot
        boolean is_active
        datetime last_verified_at
    }
    IDEA_LOGIN_OTP_CHALLENGE {
        uuid id PK
        varchar normalized_email
        bigint external_user_id
        varchar code_hash
        datetime expires_at
        datetime used_at
        smallint failed_attempts
    }
    IDEA_LOGIN_AUDIT_LOG {
        bigint id PK
        bigint external_user_id
        varchar event
        datetime occurred_at
        json details
    }
    AX_USER_TEAM_LOGIN_VIEW {
        bigint user_id PK
        varchar user_email
        varchar primary_email
        varchar role
        bigint participant_id
        bigint round_id
        bigint team_id
    }
    USER_ROUND_TEAM_VIEW {
        bigint participant_id PK
        bigint user_id
        bigint round_id
        bigint team_id
        varchar round_status
    }
```

인증·감사 테이블은 의도적으로 부모 VIEW와 FK를 맺지 않는다. 세션 사용자는
`LocalUserMapping.external_user_id`로 부모 사용자와 매핑하고, 로그인 및 중요 쓰기 전에 VIEW를
다시 검증한다.

## 3. PRD·템플릿·코멘트

```mermaid
erDiagram
    PRD_TEMPLATES ||--o{ PRD_TEMPLATE_SECTIONS : contains
    PRD_TEMPLATE_SECTIONS ||--o{ PRD_TEMPLATE_QUESTIONS : contains

    PRDS ||--o{ PRD_PARTICIPANTS : grants
    PRDS ||--o{ PRD_SECTIONS : contains
    PRD_SECTIONS ||--o{ PRD_QUESTIONS : contains
    PRD_QUESTIONS ||--o| PRD_ANSWERS : has
    PRDS ||--o{ PRD_COMMENTS : has
    PRD_QUESTIONS o|--o{ PRD_COMMENTS : targets
    PRDS ||--o{ PRD_CHANGE_HISTORY : records
    PRDS ||--o{ PRD_STATUS_AUDIT_LOGS : audits

    PRDS {
        bigint id PK
        varchar prd_type
        varchar status
        bigint version
        bigint round_id
        bigint team_id
        bigint creator_user_id
        varchar creation_idempotency_key
        boolean is_deleted
        datetime deleted_at
    }
    PRD_PARTICIPANTS {
        bigint id PK
        bigint prd_id FK
        bigint user_id
        bigint participant_id
        varchar role
        int version
    }
    PRD_SECTIONS {
        bigint id PK
        bigint prd_id FK
        int position
        boolean is_deleted
    }
    PRD_QUESTIONS {
        bigint id PK
        bigint section_id FK
        int position
        boolean is_completed
        boolean is_held
        bigint version
    }
    PRD_ANSWERS {
        bigint id PK
        bigint question_id FK, UK
        text content
        bigint updated_by_user_id
    }
    PRD_COMMENTS {
        bigint id PK
        bigint prd_id FK
        bigint section_question_id FK
        bigint author_user_id
        varchar comment_type
        boolean is_contribution_eligible
        int version
        boolean is_deleted
    }
```

`prd_deletion_audit_logs`는 PRD FK가 없는 독립 삭제 사실 원장이다. PRD 영구 삭제 후에도 삭제된
PRD ID와 제목·사용자 snapshot을 보존하기 위해 ER 관계 밖에 둔다.

## 4. 브레인스토밍과 버전 보드

```mermaid
erDiagram
    PRDS ||--o{ BRAINSTORM_CANVASES : owns
    BRAINSTORM_CANVASES o|--o{ BRAINSTORM_CANVASES : derived_from
    BRAINSTORM_CANVASES ||--o{ BRAINSTORM_NODES : contains
    PRD_SECTIONS o|--o{ BRAINSTORM_NODES : classifies
    BRAINSTORM_CANVASES ||--o{ BRAINSTORM_CONNECTIONS : contains
    BRAINSTORM_NODES ||--o{ BRAINSTORM_CONNECTIONS : node_a
    BRAINSTORM_NODES ||--o{ BRAINSTORM_CONNECTIONS : node_b
    BRAINSTORM_CANVASES ||--o{ BRAINSTORM_USER_VIEWPORTS : stores
    BRAINSTORM_CANVASES ||--o{ BRAINSTORM_CHANGE_LOGS : streams
    BRAINSTORM_CANVASES ||--o{ BRAINSTORM_AUDIT_LOGS : audits

    BRAINSTORM_CANVASES {
        bigint id PK
        bigint prd_id FK
        int version_number
        bigint source_canvas_id FK
        bigint created_by_user_id
        varchar creation_idempotency_key
        int display_order
        boolean is_deleted
        datetime deleted_at
    }
    BRAINSTORM_NODES {
        uuid id PK
        uuid lineage_id
        bigint canvas_id FK
        bigint section_id FK
        varchar node_type
        varchar status
        bigint author_id
        bigint assignee_id
        bigint version
        boolean is_deleted
    }
    BRAINSTORM_CONNECTIONS {
        uuid id PK
        bigint canvas_id FK
        uuid node_a_id FK
        uuid node_b_id FK
        bigint version
        boolean is_deleted
    }
    BRAINSTORM_USER_VIEWPORTS {
        bigint id PK
        bigint canvas_id FK
        bigint user_id
        decimal viewport_x
        decimal viewport_y
        decimal zoom_level
    }
    BRAINSTORM_CHANGE_LOGS {
        bigint id PK
        bigint canvas_id FK
        uuid operation_id
        bigint actor_user_id
        varchar action
        varchar target_type
        varchar target_id
    }
```

`(prd_id, version_number)`는 유일하다. 최초 진입은 활성 캔버스를 `display_order`, version 역순,
ID 역순으로 정렬한 첫 보드를 연다. 첫 보드만 최신·편집 가능하며, 순서 변경은 PRD 행 잠금 안에서
전체 활성 ID를 검증해 원자적으로 적용한다. 최신 보드는 소프트 삭제하고 다음 보드를 승격하되
마지막 활성 보드는 삭제할 수 없다. 복제된 메모는 새 PK와 resource version을 받지만 동일한
`lineage_id`를 유지한다. 연결선은 자기 연결을 금지하고 정렬된 두 node 조합을 유일하게 유지한다.

## 5. AI 작업·코칭·PRD 반영·기여도

```mermaid
erDiagram
    AI_PROMPTS ||--o{ AI_JOBS : configures
    PRDS ||--o{ AI_JOBS : requests
    AI_JOBS o|--o{ AI_USAGE_LOGS : records
    PRDS ||--o{ AI_USAGE_LOGS : aggregates

    PRDS ||--o{ AI_COACH_CONVERSATIONS : has
    PRD_SECTIONS o|--o{ AI_COACH_CONVERSATIONS : scopes
    AI_COACH_CONVERSATIONS ||--o{ AI_COACH_MESSAGES : contains
    AI_JOBS o|--o{ AI_COACH_MESSAGES : produces

    PRDS ||--o{ AI_PRD_APPLY_RECORDS : applies
    BRAINSTORM_CANVASES ||--o{ AI_PRD_APPLY_RECORDS : sources
    AI_JOBS ||--o| AI_PRD_APPLY_RECORDS : previews
    AI_PRD_APPLY_RECORDS ||--o{ AI_PRD_APPLY_ITEMS : contains
    PRD_QUESTIONS ||--o{ AI_PRD_APPLY_ITEMS : updates

    PRDS ||--o{ CONTRIBUTION_EVALUATIONS : evaluates
    PRD_STATUS_AUDIT_LOGS ||--|| CONTRIBUTION_EVALUATIONS : completes
    AI_JOBS o|--o| CONTRIBUTION_EVALUATIONS : processes
    CONTRIBUTION_EVALUATIONS ||--o{ CONTRIBUTION_USER_SCORES : totals
    CONTRIBUTION_EVALUATIONS ||--o{ CONTRIBUTION_COMMENT_SCORES : explains
    PRD_COMMENTS ||--o{ CONTRIBUTION_COMMENT_SCORES : evaluates

    AI_JOBS {
        uuid id PK
        bigint prd_id FK
        bigint prompt_id FK
        bigint user_id
        varchar feature_type
        varchar action_type
        varchar status
        varchar idempotency_key
        datetime lease_expires_at
    }
    CONTRIBUTION_EVALUATIONS {
        bigint id PK
        bigint prd_id FK
        bigint completion_audit_id FK, UK
        uuid job_id FK, UK
        int calculation_version
        bigint prd_version
        varchar status
        varchar input_fingerprint
    }
    CONTRIBUTION_USER_SCORES {
        bigint id PK
        bigint evaluation_id FK
        bigint user_id
        decimal memo_contribution
        decimal comment_contribution
        decimal total_score
    }
    AI_PRD_APPLY_ITEMS {
        bigint id PK
        uuid record_id FK
        bigint question_id FK
        bigint question_version_before
        decimal confidence
        json source_nodes
    }
```

AI 작업은 웹 요청과 별도 worker가 PostgreSQL 행 잠금과 lease로 처리한다. 기여도 계산은 완료
감사 로그마다 하나의 평가를 만들고, 재개 후 재완료하면 새 계산 version을 생성한다.

## 6. 삭제 연쇄와 보존

| 부모 행 삭제 | 주요 처리 |
|---|---|
| PRD 영구 삭제 | 참여자·섹션·질문·답변·코멘트·캔버스·AI 작업·상세 기여도는 CASCADE 또는 정리 서비스로 삭제 |
| PRD 삭제 감사 | PRD FK가 없어 최소 삭제 사실은 유지 |
| 질문 삭제 | 답변 CASCADE, 질문 연결 코멘트는 `SET_NULL` |
| 캔버스 삭제 | 노드·연결선·viewport·변경·감사 로그 CASCADE |
| AI prompt | 연결된 작업이 있으면 `PROTECT` |
| AI PRD 반영 질문 | 반영 근거 보존을 위해 `PROTECT` |
| 기여도 대상 코멘트 | 평가 근거 보존을 위해 `PROTECT` |

소프트 삭제와 영구 삭제의 세부 실행 순서는 `run_midnight_maintenance`와
`cleanup_background_data` 서비스가 담당한다.
