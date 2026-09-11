# 로컬 개발 환경

## 요구 사항

- Python 3.12 이상
- PostgreSQL
- Git
- 선택 사항: DBeaver 또는 다른 PostgreSQL 관리 도구

## 저장소 준비

```powershell
git clone <repository-url>
Set-Location idea-developer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

PowerShell에서 스크립트 실행이 차단되면 가상환경을 활성화하지 않고 `.\.venv\Scripts\python.exe`를 직접 사용할 수 있습니다.

## PostgreSQL 준비

로컬 개발용 데이터베이스와 사용자를 생성하고 `.env`의 `POSTGRES_*` 값과 일치시킵니다. 예시 이름은 `.env.example`을 참고하되 비밀번호는 직접 생성한 값을 사용하세요.

애플리케이션 테이블은 `POSTGRES_OPTIONS`에 지정된 schema를 사용합니다. 해당 schema를 생성할 권한이 있는 사용자로 최초 migration을 실행해야 합니다.

## 환경변수

```powershell
Copy-Item .env.example .env
```

필수 확인 항목:

- `DJANGO_SECRET_KEY`: 충분히 긴 임의 문자열
- `DJANGO_DEBUG`: 로컬 개발에서는 `true`
- `POSTGRES_*`: 로컬 애플리케이션 DB 접속 정보
- `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`: 접속 주소

외부 연동 환경에서만 필요한 항목:

- `INTEGRATION_DB_*`: 외부 VIEW가 있는 PostgreSQL의 읽기 전용 계정
- `INTEGRATION_ACTIVE_ROUND_STATUSES`: 외부 시스템의 실제 활성 회차 상태값
- `GEMINI_API_KEY`: Gemini 기반 AI 기능을 사용할 때만 설정

`.env`와 실제 비밀값은 커밋하지 않습니다.

## 초기화와 실행

```powershell
python manage.py migrate
python manage.py runserver
```

기본 접속 주소는 `http://127.0.0.1:8000`입니다.

## 테스트

```powershell
python manage.py test --settings=config.settings.test
python -m ruff check .
```

특정 테스트만 실행하려면 테스트 모듈을 지정합니다.

```powershell
python manage.py test tests.test_prd_api --settings=config.settings.test
```

## 선택 기능

AI 작업을 처리하려면 웹 서버와 별도로 worker를 실행합니다.

```powershell
python manage.py run_ai_worker
```

데모 데이터 명령은 대상 데이터베이스가 개발 환경인지 확인한 후 사용하세요.

## 종료

개발 서버는 `Ctrl+C`로 종료하고, 활성화된 가상환경은 `deactivate`로 해제합니다.
