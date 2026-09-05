# 04. 프로젝트 구조

코드 생성 후 목표 구조입니다. 초기에는 일부 폴더만 존재할 수 있습니다.

```text
idea-developer/
├── config/                 # Django settings, urls, wsgi
├── apps/
│   ├── accounts/           # 이메일 OTP, 로컬 사용자 매핑, 세션
│   ├── integration/        # 읽기 전용 VIEW와 IntegrationContext
│   ├── prds/               # PRD, 홈 KPI, 질문, 답변, 코멘트, 권한
│   ├── brainstorm/         # 메모, 연결선, 버전 보드, polling, 감사 기록
│   ├── ai/                 # AI 프롬프트, 작업, 사용 로그, 기여도
│   └── jobs/               # PostgreSQL 작업 worker와 정리 작업
├── templates/              # Django·Bootstrap 화면
├── static/
│   ├── css/                # 공통 및 앱별 CSS
│   └── js/                 # 일반 JS와 React CDN 앱
├── tests/                  # 앱 간 통합 테스트
├── requirements/           # base, dev, production 의존성
├── docs/
│   ├── specs/              # 승인된 백엔드 시나리오
│   ├── integration/        # VIEW 규격과 이관 문서
│   └── team-practice/      # 팀 Git 연습
├── manage.py
├── .env.example
└── README.md
```

## 파일 소유가 아니라 기능 소유

팀원이 특정 파일을 영구 소유하지 않습니다. 작업마다 담당 기능을 정하고 필요한 파일만 수정합니다. 한 파일을 여러 기능이 고쳐야 한다면 먼저 담당자끼리 범위를 합의합니다.

## Django app 경계

- 다른 app의 모델을 여러 화면에서 직접 복잡하게 조회하지 않습니다.
- 권한과 비즈니스 규칙은 service/policy 계층에 모읍니다.
- VIEW 조회는 `integration` app 밖에 흩어놓지 않습니다.
- template은 화면, service는 규칙, model은 데이터 제약을 담당합니다.
- React CDN 코드는 브레인스토밍에만 사용합니다.
