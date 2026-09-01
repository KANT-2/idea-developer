# 01. 개발 환경 설치

## 1. 필수 프로그램

- Git
- Python 3.12 권장
- PostgreSQL 16 권장
- VS Code 또는 원하는 편집기

설치 확인:

```bash
git --version
python3 --version
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

## 5. 환경변수

```bash
cp .env.example .env
```

`.env`는 각자 컴퓨터에서만 수정합니다. 절대 Git에 올리지 않습니다. 실제 DB 비밀번호와 AI API 키는 팀장이 안전한 별도 채널로 전달합니다.

## 6. 코드가 생성된 뒤의 기본 실행

```bash
python -m pip install --upgrade pip
pip install -r requirements/dev.txt
python manage.py migrate
python manage.py check
python manage.py runserver
```

브라우저에서 `http://127.0.0.1:8000/`을 엽니다.

## 7. 작업 종료

```bash
deactivate
```
