# 주요 기능 시퀀스

## 1. 로그인과 IntegrationContext

```mermaid
sequenceDiagram
    actor U as 사용자
    participant UI as Django Login UI
    participant A as Accounts Service
    participant V as Parent VIEW Repository
    participant DB as Child PostgreSQL

    U->>UI: 이메일 입력 또는 DEBUG 사용자 검색
    UI->>A: 인증 요청
    A->>V: 활성·승인 사용자 확인
    V-->>A: external user_id
    A->>DB: 최소 LocalUser 매핑·감사 기록
    A-->>UI: Django session 생성
    UI-->>U: /ideas/ 이동
    U->>UI: 제품 API 요청
    UI->>A: session → external user_id
    A->>V: user_id + 선택 round_id 검증
    V-->>A: IntegrationContext
```

VIEW 장애나 참가정보 불일치가 발생하면 검증이 필요한 쓰기 요청은 실행하지 않는다.

## 2. PRD 생성과 Slack 참여 알림

```mermaid
sequenceDiagram
    actor U as owner
    participant UI as 새 PRD 화면
    participant API as PRD API
    participant V as Parent VIEW Repository
    participant DB as PostgreSQL
    participant S as Parent Slack Module

    U->>UI: 유형·기본정보·참여자 입력
    UI->>API: POST + Idempotency-Key
    API->>V: 생성자·회차·팀·참여자 검증
    V-->>API: 유효한 외부 사용자 정보
    API->>DB: transaction 시작
    API->>DB: PRD + owner + 참여자 + 템플릿 복제
    DB-->>API: commit
    API-->>UI: 생성된 PRD 반환
    UI-->>U: PRD 작성 화면 이동
    API->>S: commit 이후 참여자 DM
    alt Slack 일시 실패
        S->>S: 최대 3회 재시도
        S-->>API: 최종 실패 로그
        Note over API,DB: PRD 저장은 유지
    end
```

동일 key·동일 payload의 재요청은 최초 생성 결과를 재사용한다.

## 3. PRD 질문 공동 편집

```mermaid
sequenceDiagram
    actor A as 편집자 A
    actor B as 편집자 B
    participant API as PRD API
    participant DB as PostgreSQL

    A->>API: 질문 조회
    B->>API: 질문 조회
    API-->>A: answer, version=3
    API-->>B: answer, version=3
    A->>API: 답변 저장, version=3
    API->>DB: row lock + version 확인
    DB-->>API: 저장, version=4
    API-->>A: 성공 version=4
    B->>API: 다른 답변 저장, version=3
    API->>DB: row lock + version 확인
    DB-->>API: current version=4
    API-->>B: 409 + 최신 질문
    B->>B: 최신값 비교·재편집
```

서버는 마지막 요청으로 조용히 덮어쓰는 last-write-wins 방식을 사용하지 않는다.

## 4. 브레인스토밍 변경과 polling

```mermaid
sequenceDiagram
    actor A as 사용자 A
    actor B as 사용자 B
    participant RA as React Canvas A
    participant RB as React Canvas B
    participant API as Brainstorm API
    participant DB as PostgreSQL

    A->>RA: 메모 이동
    RA->>API: PATCH 최종 좌표 + node version
    API->>DB: 권한·완료 상태·version 검증
    DB->>DB: node 갱신 + change event cursor 증가
    API-->>RA: 최신 node
    RA->>RA: 화면 즉시 반영
    RB->>API: GET events?cursor=N
    API->>DB: N 이후 event 조회
    API-->>RB: 위치 변경 event + cursor
    RB->>RB: 화면 반영
    alt cursor 무효 또는 재연결
        RB->>API: 전체 canvas 조회
        API-->>RB: nodes + connections + counts
    end
```

드래그 중간 좌표는 저장하지 않고 종료 좌표만 전송한다.

## 5. 보류와 연결선 정리

```mermaid
sequenceDiagram
    actor U as 편집 사용자
    participant UI as React Canvas
    participant API as Brainstorm API
    participant DB as PostgreSQL

    U->>UI: 보류 선택
    UI->>API: node version + connection versions
    API->>DB: transaction + 관련 행 잠금
    DB->>DB: node/연결선 version 집합 확인
    alt 모두 일치
        DB->>DB: status=held, section=null
        DB->>DB: 연결선 영구 삭제 + 감사 기록
        DB-->>API: commit
        API-->>UI: 변경 node와 삭제 연결 반환
        UI->>UI: 메모를 보류 구역으로 즉시 이동
    else 집합 변경
        DB-->>API: rollback
        API-->>UI: 409 connection_version_conflict
        UI->>API: 보드 재조회
    end
```

## 6. AI 코치와 변경안 승인

```mermaid
sequenceDiagram
    actor U as owner/editor
    participant UI as AI 코치 패널
    participant API as AI API
    participant DB as PostgreSQL
    participant W as AI Worker
    participant G as Gemini

    U->>UI: 질문 입력
    UI->>API: chat 요청
    API->>DB: 대화 append + AI job 생성
    API-->>UI: job_id
    W->>DB: job claim + lease
    W->>G: system instruction + 제한된 PRD context + 최근 3턴
    G-->>W: 구조화된 응답
    W->>W: schema·반환 ID 검증
    W->>DB: assistant message + proposal + usage log
    UI->>API: job 상태 polling
    API-->>UI: 성공 응답·변경안
    U->>UI: 변경안 승인 또는 거절
    alt 승인
        UI->>API: apply + question version
        API->>DB: version 확인 후 답변 저장
        API-->>UI: 최신 질문
    else 거절
        UI->>API: decline
        API->>DB: 거절 기록, PRD 미변경
    end
```

## 7. 브레인스토밍 PRD 반영

```mermaid
sequenceDiagram
    actor U as owner/editor
    participant UI as 반영 미리보기
    participant API as PRD Apply API
    participant DB as PostgreSQL
    participant W as AI Worker

    U->>UI: 섹션·메모 선택
    UI->>API: preview 요청 + node/question versions
    API->>DB: 대상·권한·상태 검증, job 생성
    W->>DB: 현재 답변·선택 메모·연결 조회
    W->>DB: 통합 draft와 근거 저장
    API-->>UI: 질문별 비교·source nodes
    U->>UI: 저장할 질문만 승인
    UI->>API: preview_request_id + versions + Idempotency-Key
    API->>DB: 모든 version 재검증
    alt 변경 없음
        DB->>DB: 승인 질문 저장 + 반영 기록
        API-->>UI: 성공
    else 미리보기 후 변경됨
        DB-->>API: rollback
        API-->>UI: 409 + 최신 데이터
    end
```

## 8. 완료·기여도·재개

```mermaid
sequenceDiagram
    actor O as owner
    participant API as PRD API
    participant DB as PostgreSQL
    participant W as AI Worker

    O->>API: 완료 요청
    API->>DB: 상태·권한·미완료 질문 검사
    DB->>DB: status=completed + 감사 기록 + version 증가
    DB-->>API: commit
    API->>DB: 기여도 job 생성
    API-->>O: 완료 성공
    W->>DB: 반영 메모 lineage·적격 코멘트 조회
    W->>DB: 메모·코멘트 정규화 + 50:50 결과 새 버전 저장
    alt AI 코멘트 평가 실패
        W->>DB: contribution_status=failed
        Note over DB: PRD completed 유지
    end
    O->>API: 이유와 함께 재개
    API->>DB: completed 확인 + 감사 기록
    DB-->>API: in_progress, 기존 평가 버전 보존
```

## 9. 30일 삭제와 자정 유지보수

```mermaid
sequenceDiagram
    actor U as owner
    participant UI as PRD 화면·휴지통
    participant API as PRD API
    participant DB as PostgreSQL
    participant M as Midnight Maintenance

    U->>UI: PRD 삭제 확인
    UI->>API: delete + version
    API->>DB: is_deleted=true, deleted_at 기록
    API-->>UI: 삭제 완료
    UI-->>U: 홈 이동
    U->>UI: 휴지통 삭제 확인
    UI->>API: purge 요청
    API->>DB: purge_requested_at 기록
    API-->>UI: 삭제 완료
    M->>DB: 매일 00:00 보존기간 경과 조회
    alt 대상 있음
        M->>DB: 관련 상세 데이터 삭제 + 독립 삭제 감사 보존
    else 대상 없음
        M-->>M: 삭제 수 0, 정상 종료
    end
```
