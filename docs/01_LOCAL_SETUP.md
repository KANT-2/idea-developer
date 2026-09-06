# 01. 개발 환경 설치

## 1. 필수 프로그램

- Git
- Python 3.12 권장
- PostgreSQL 16 권장
- DBeaver Community 또는 PostgreSQL 관리 도구
- VS Code 또는 원하는 편집기

설치 확인:

```bash
git --version
python3 --version
# psql CLI를 설치한 경우에만 확인
psql --version
```

## 2. Git 최초 설정

아래 이름과 이메일은 본인 정보로 바꿉니다. 이메일은 GitHub 계정과 연결된 주소를 권장합니다.

```bash
git config --global user.name "내 이름"
git config --global user.email "내이메일@example.com"
git config --global init.defaultBranch main
```

확인:

```bash
git config --global --list
```

## 3. 저장소 clone

```bash
cd <프로젝트를-둘-폴더>
git clone https://github.com/KANT-2/idea-developer.git
cd idea-developer
```

## 4. Python 가상환경

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

활성화되면 터미널 앞에 `(.venv)`가 보입니다.

## 5. DBeaver에서 로컬 DB 준비

1. DBeaver에서 로컬 PostgreSQL 서버에 관리자 계정으로 연결합니다.
2. SQL 편집기를 열고 아래 SQL의 비밀번호를 개인 개발용 값으로 바꿔 실행합니다.
3. 이미 사용자나 DB가 있으면 새로 만들지 말고 소유자와 접속 권한만 확인합니다.

```sql
CREATE USER idea_developer WITH PASSWORD '개인-로컬-비밀번호';
CREATE DATABASE idea_developer OWNER idea_developer;
```

`CREATE DATABASE`가 transaction 안에서 실행될 수 없다는 오류가 나면 DBeaver의 자동 commit을
켜거나 두 문장을 각각 실행합니다. Database Navigator에서 새 연결을 만들어 다음 값을 확인합니다.

```text
Host: 127.0.0.1
Port: 5432
Database: idea_developer
Username: idea_developer
Password: 위에서 정한 개인 로컬 비밀번호
```

연결한 `idea_developer` DB에서 `scripts/bootstrap_database.sql`을 실행해 애플리케이션 schema를
준비합니다. 이 스크립트는 사용자나 데이터베이스를 만들지 않고 `idea_developer` schema만
생성합니다.

## 6. 환경변수

macOS/Linux:

```bash
cp .env.example .env
```

`.env`는 각자 컴퓨터에서만 수정합니다. 절대 Git에 올리지 않습니다. 실제 DB 비밀번호와 AI API 키는 팀장이 안전한 별도 채널로 전달합니다.

Windows PowerShell에서는 다음 명령을 사용합니다.

```powershell
Copy-Item .env.example .env
```

`.env`의 `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`,
`POSTGRES_PORT`를 DBeaver에서 확인한 로컬 접속값과 맞춥니다. 부모 VIEW 접속값과 Gemini 키는
해당 연동을 사용할 사람만 별도 보안 채널에서 받아 입력합니다.

## 7. 의존성 설치와 기본 실행

```bash
python -m pip install --upgrade pip
pip install -r requirements/development.txt
python manage.py migrate
python manage.py check
python manage.py runserver
```

브라우저에서 `http://127.0.0.1:8000/`을 엽니다. 기본 경로는 로그인 상태에 따라 로그인 또는
`/ideas/`로 이동합니다.

## 8. 선택 사항: 데모 데이터

부모 VIEW가 연결되어 있거나 개발 fixture fallback 사용자가 준비된 경우 다음 명령으로 반복 실행
가능한 예시 PRD·참여자·메모를 만들 수 있습니다.

```bash
python manage.py seed_demo_workspace
```

## 9. 작업 종료

```bash
deactivate
```
