# 프로젝트 구조

## 디렉터리 구성

```text
idea-developer/
├── apps/
│   ├── accounts/       # 로그인, 로컬 사용자 매핑, 역할 권한
│   ├── ai/             # AI provider, 작업, 프롬프트, 사용량, 기여도
│   ├── audit/          # 감사 기록
│   ├── brainstorm/     # 브레인스토밍 보드, 메모, 연결선, 동시성
│   ├── common/         # 공통 응답과 기반 유틸리티
│   ├── dashboard/      # 대시보드 관련 구성
│   ├── integration/    # 외부 PostgreSQL VIEW와 컨텍스트 해석
│   ├── jobs/           # 백그라운드 작업 기반
│   └── prds/           # PRD, 참여자, 질문·답변, 홈, 상태와 권한
├── config/             # Django settings, URL, WSGI/ASGI
├── templates/          # 서버 렌더링 HTML
├── static/             # CSS와 브라우저 JavaScript
├── tests/              # 단위·통합·API 회귀 테스트
├── docs/               # 제품과 기술 문서
├── requirements/       # base, development, production 의존성
├── scripts/            # 개발·운영 보조 스크립트
├── manage.py
└── .env.example
```

## 애플리케이션 경계

### accounts

로그인 세션과 외부 사용자 ID의 최소 매핑을 관리합니다. 제품 역할 권한 행렬도 이 영역에 있습니다. 외부 사용자의 상세 프로필을 로컬 사용자 테이블에 복제하지 않습니다.

### integration

외부 시스템의 사용자, 회차, 팀 VIEW를 읽고 요청에 사용할 `IntegrationContext`를 만듭니다. 외부 VIEW는 `managed=False`인 읽기 전용 모델이며 이 프로젝트의 migration 대상이 아닙니다.

### prds

PRD, 템플릿, 참여자, 섹션, 질문, 답변, 코멘트, 상태 변경, 홈 조회를 담당합니다. 데이터 제약은 모델과 migration에 두고, 생성·권한·상태 전이는 service 계층에서 검증합니다.

### brainstorm

PRD별 보드, 메모, 연결선, 위치, 담당자, 변경 이력과 동시성 제어를 담당합니다. 접근 권한은 PRD 참여 권한을 재사용합니다.

### ai와 jobs

AI 요청을 작업으로 등록하고 worker가 provider를 호출합니다. 요청·결과·사용량·재시도 상태를 저장하며, AI 결과를 PRD에 적용하기 전에 서버 데이터와 version을 다시 검증합니다.

## 요청 처리 흐름

```text
Browser
  → Django URL/View
  → Context 및 권한 확인
  → Service 계층의 업무 규칙
  → Django Model/PostgreSQL
  → JSON 응답 또는 Template 렌더링
```

외부 사용자 정보가 필요한 요청은 `integration` repository를 통해 VIEW를 조회합니다. 쓰기 데이터는 애플리케이션 소유 PostgreSQL schema에만 저장합니다.

## 코드 배치 원칙

- `models.py`: 저장 구조, 관계, 인덱스, DB 제약
- `services.py`: 여러 모델에 걸친 업무 규칙과 트랜잭션
- `views.py`: HTTP 입력 파싱, 인증, 응답 변환
- `repository.py`: 외부 데이터 소스 접근
- `templates/`: 접근 가능한 HTML 구조와 서버 렌더링 값
- `static/`: 화면 동작과 스타일
- `tests/`: 권한, 오류, 데이터 제약, 회귀 시나리오

기능을 변경할 때는 이 경계를 유지하고, 권한 검사를 브라우저 코드에만 의존하지 않아야 합니다.
