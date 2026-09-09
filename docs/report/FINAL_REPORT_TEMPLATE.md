# idea-developer 최종보고서

> 작성 기준일: YYYY-MM-DD
>
> 기준 브랜치: `develop`
>
> 기준 commit: `<40자리 commit SHA>`
>
> 작성자: `<팀명 또는 작성자>`

## 1. 프로젝트 개요

### 1.1 배경과 문제 정의

- 기존 PRD 작성 과정에서 해결하려는 문제
- 아이디어 발산, 공동 편집, 문서 통합과 기여도 확인이 필요한 이유
- 대상 사용자와 사용 환경

### 1.2 목표

- 독립 실행 가능한 Django 기반 `idea-developer` 구축
- PRD 작성, 브레인스토밍, AI 코칭과 협업 기능 통합
- 부모 시스템과 안전하게 연결할 수 있는 명확한 연동 경계 제공

### 1.3 범위

구현 기능과 현재 제공하지 않는 기능을 [기능 명세](../FUNCTIONAL_SPEC.md)의 구분에 따라 작성한다.
확정되지 않은 기능을 완료 항목에 포함하지 않는다.

## 2. 요구사항과 Business Rule

### 2.1 핵심 요구사항

| ID | 요구사항 | 구현 결과 | 근거 |
|---|---|---|---|
| FR-01 | 로그인과 외부 사용자 연동 | `<완료/부분/미구현>` | `<코드·테스트>` |
| FR-02 | PRD 생성·편집·완료 |  |  |
| FR-03 | 참여자와 역할 권한 |  |  |
| FR-04 | 브레인스토밍 협업 |  |  |
| FR-05 | AI 코칭·진단·반영 |  |  |
| FR-06 | 기여도 계산 |  |  |
| FR-07 | 알림·삭제·유지보수 |  |  |

상세 구현 근거는 [요구사항 추적표](../REQUIREMENTS_TRACEABILITY.md)에 연결한다.

### 2.2 핵심 정책

- PRD 역할과 완료 후 잠금
- 회차 없는 PRD와 회차 팀 PRD의 접근 차이
- version 충돌과 idempotency key
- 메모 상태, 보드 버전과 lineage
- AI 미리보기 후 명시적 승인
- 50:50 기여도와 관리자 공개
- 30일 소프트 삭제와 자정 유지보수

## 3. 사용자와 주요 기능

역할별 권한과 유스케이스는 [기능 구성도·유스케이스](USE_CASES.md)를 삽입하거나 참조한다.

| 사용자 | 주요 목적 | 대표 기능 |
|---|---|---|
| owner | PRD 운영 | 생성, 편집, 참여자 관리, 완료·재개, 삭제 |
| editor | 공동 작성 | 답변 편집, 브레인스토밍, AI 요청·반영, 코멘트 |
| tutor | 지도 | 담당 PRD 조회, 학생 검색, 지도·리뷰 코멘트, 메모 생성 |
| viewer | 열람 | 참여 PRD와 브레인스토밍 조회 |
| administrator | 운영 | 재개, 복원 정책, 기여도 조회·재평가 |

## 4. 화면 설계와 사용자 흐름

[화면 흐름도](SCREEN_FLOW.md)를 기준으로 다음 화면의 목적과 핵심 상호작용을 설명한다.

1. 로그인
2. 홈 대시보드와 tutor 관리
3. 새 PRD 만들기
4. PRD 작성·AI 코치·코멘트
5. 브레인스토밍 보드
6. 휴지통과 복구

실제 화면 캡처에는 개인정보·실제 이메일·비밀값이 보이지 않게 한다.

## 5. 시스템 설계

### 5.1 기술 스택

| 계층 | 기술 | 선택 이유 |
|---|---|---|
| Backend | Django 5.2 | 인증, ORM, migration과 template 통합 |
| UI | Django Template, Bootstrap 5.3.2 | 부모 UI 호환과 독립 실행 |
| Brainstorm UI | React·ReactDOM CDN | 상호작용이 많은 캔버스만 독립 mount |
| Database | PostgreSQL | 관계 무결성, JSON, 행 잠금과 작업 큐 |
| Collaboration | HTTP polling + version | 별도 Redis 없이 충돌 감지 |
| Background | DB job + management command worker | 웹과 동일 코드로 독립 프로세스 실행 |
| AI | Gemini provider adapter | 모델 호출과 제품 로직 분리 |

### 5.2 아키텍처와 데이터 흐름

- [시스템 아키텍처](../ARCHITECTURE.md)
- [데이터 흐름도](DATA_FLOW.md)
- [주요 시퀀스](SEQUENCE_DIAGRAMS.md)
- [상태 전이도](STATE_DIAGRAMS.md)
- [배포 구성도](DEPLOYMENT_DIAGRAM.md)

### 5.3 데이터베이스

- [ERD](../database/ERD.md)
- [데이터 사전](../database/DATA_DICTIONARY.md)
- DB 제약조건, 인덱스, soft delete와 감사 기록 설계
- 부모 VIEW가 unmanaged/read-only인 이유

## 6. 핵심 구현

### 6.1 권한과 IntegrationContext

프론트 표시와 관계없이 모든 API가 session, 외부 사용자, 회차·팀과 PRD 참여 역할을 서버에서
재검사하는 방식을 설명한다.

### 6.2 공동 편집과 충돌 처리

PRD, 질문, 참여자, 코멘트, 메모와 연결선의 version 처리 및 `409 Conflict` 이후 사용자 재확인
흐름을 설명한다.

### 6.3 AI 비동기 처리

job 생성, worker claim, Gemini 호출, JSON·ID 검증, 성공·실패·취소와 승인 반영을 설명한다.

### 6.4 브레인스토밍 버전과 기여도

캔버스 복제, lineage 유지, 반영된 accepted 메모의 중복 제거와 코멘트 의미 반영 평가를 설명한다.

## 7. 예외 처리와 보안

[예외 처리 목록](../EXCEPTION_CATALOG.md)을 바탕으로 다음 사례를 결과와 함께 정리한다.

- 인증·CSRF·권한 오류
- 부모 VIEW 장애와 fail closed
- 동시 수정과 중복 요청
- AI timeout·잘못된 JSON·ID 위조
- Slack 실패 격리
- 삭제·복구·보존기간 경계

보안 통제는 [테스트·보안·운영 품질](../QUALITY_ASSURANCE.md)의 체크리스트를 사용한다.

## 8. 테스트와 품질 결과

[테스트 결과 양식](TEST_REPORT_TEMPLATE.md)에 실행 환경, 전체 명령, 통과 수, 커버리지와 발견 결함을
기록한다. 성공 흐름뿐 아니라 권한, 경계값, 충돌과 외부 장애 결과를 포함한다.

## 9. 실행과 배포

- 로컬 재현 절차와 환경변수
- PostgreSQL 및 부모 VIEW 연결
- web, AI worker, 자정 유지보수 프로세스
- 정적 파일, HTTPS, secure cookie와 secret 관리
- 배포 후 smoke test

## 10. 결과와 한계

### 10.1 달성 결과

정량 결과와 핵심 사용자 시나리오의 완료 여부를 작성한다.

### 10.2 현재 한계

현재 사용자 화면에서 제공하지 않는 기능과 부모팀 협의 항목을 구현 완료처럼 표현하지 않는다.

### 10.3 향후 개선

확장 필요성, 영향받는 데이터와 하위 호환 방법이 확인된 항목만 작성한다.

## 11. 부록

- 기준 commit의 변경 파일 목록
- migration 목록과 적용 결과
- 환경변수 이름 목록(비밀값 제외)
- API·ERD·테스트 문서 링크
- 주요 의사결정과 변경 이력
