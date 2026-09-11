# Idea Developer

Idea Developer는 아이디어를 구조화된 PRD(Product Requirements Document)로 발전시키는 Django 웹 애플리케이션입니다. PRD 작성, 참여자 협업, 브레인스토밍 보드, AI 기반 분석과 초안 생성, 완료 후 기여도 평가를 하나의 작업 흐름으로 제공합니다.

## 주요 기능

- 이메일 OTP 로그인과 외부 사용자 정보 연동
- PRD 생성, 질문별 답변 작성, 상태·버전·변경 이력 관리
- owner, editor, tutor, viewer 역할 기반 접근 제어
- 메모와 연결선을 사용하는 브레인스토밍 보드
- AI 코칭, 아이디어 분석·분류, PRD 답변 초안 생성
- 홈 대시보드, 진행률, 마감일, 최근 활동 표시
- 완료된 PRD의 참여자 기여도 평가
- 소프트 삭제, 복원, 보관기간 만료 데이터 정리

## 기술 구성

| 구분 | 기술 |
| --- | --- |
| 백엔드 | Python, Django |
| 데이터베이스 | PostgreSQL |
| 프론트엔드 | Django Templates, Bootstrap, Vanilla JavaScript, React(브레인스토밍) |
| AI | Gemini API 어댑터 |
| 품질 관리 | Django Test, Coverage, Ruff |

## 빠른 실행

### 1. 준비 사항

- Python 3.12 이상
- PostgreSQL
- Git

### 2. 가상환경과 패키지 설치

Windows PowerShell 기준입니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. 환경변수 설정

```powershell
Copy-Item .env.example .env
```

`.env`에서 `DJANGO_SECRET_KEY`와 `POSTGRES_*` 값을 로컬 환경에 맞게 설정합니다. 외부 사용자·회차 VIEW를 사용하는 환경에서는 `INTEGRATION_DB_*`와 `INTEGRATION_ACTIVE_ROUND_STATUSES`도 설정해야 합니다. Gemini 기능을 사용하지 않는다면 `GEMINI_API_KEY`는 비워 둘 수 있습니다.

실제 비밀번호, API 키, `.env` 파일은 Git에 커밋하지 마세요.

### 4. 데이터베이스 초기화와 서버 실행

```powershell
python manage.py migrate
python manage.py runserver
```

브라우저에서 [http://127.0.0.1:8000](http://127.0.0.1:8000)에 접속합니다.

## 테스트와 코드 품질

```powershell
python manage.py test --settings=config.settings.test
python -m ruff check .
```

테스트 환경은 외부 PostgreSQL VIEW 대신 fixture repository를 사용하므로 외부 시스템 연결 없이 실행할 수 있습니다.

## 백그라운드 작업

```powershell
python manage.py run_job_worker
python manage.py run_midnight_maintenance
```

첫 명령은 AI 작업을 처리하고, 두 번째 명령은 기한이 지난 PRD와 보관기간이 만료된 데이터를 정리합니다. 운영 환경에서는 서비스 관리자나 작업 스케줄러로 실행합니다.

## 프로젝트 구조

```text
idea-developer/
├── apps/               # Django 도메인 애플리케이션
├── config/             # 프로젝트 설정과 URL 구성
├── templates/          # Django HTML 템플릿
├── static/             # CSS와 JavaScript
├── tests/              # 자동화 테스트
├── docs/               # 기능, API, 데이터, 운영 문서
├── requirements/       # 환경별 Python 의존성
├── manage.py
└── .env.example
```

도메인별 상세 구조는 [프로젝트 구조](docs/04_PROJECT_STRUCTURE.md), 전체 기술 문서는 [문서 안내](docs/README.md)를 참고하세요.

## 외부 시스템 연동

애플리케이션은 외부 시스템의 사용자·회차·팀 정보를 PostgreSQL VIEW로 읽을 수 있습니다.

- `public.ax_user_team_login_view`: 사용자 인증·승인 상태
- `public.user_round_team_view`: 회차 참여와 팀 정보

두 VIEW는 조회 전용이며 이 프로젝트에서 생성, 수정, 삭제하지 않습니다. 자세한 내용은 [VIEW 연동 안내](docs/integration/VIEW_GUIDE.md)를 참고하세요.

## 추가 문서

- [기능 명세](docs/FUNCTIONAL_SPEC.md)
- [시스템 아키텍처](docs/ARCHITECTURE.md)
- [API 문서](docs/api/README.md)
- [ERD](docs/database/ERD.md)
- [데이터 사전](docs/database/DATA_DICTIONARY.md)
- [예외 처리](docs/EXCEPTION_CATALOG.md)
- [품질 보증](docs/QUALITY_ASSURANCE.md)

## 기여

기능 변경에는 테스트와 관련 문서 변경을 함께 포함합니다. 자세한 절차는 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요.
