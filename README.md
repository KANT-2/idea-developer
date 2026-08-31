# Idea Developer

아이디어 디벨로퍼를 독립 Django 시스템으로 개발하는 팀 저장소입니다.

- Backend: Django 5.2.x
- UI: Django Template + Bootstrap 5.3.2
- Database: PostgreSQL
- 브레인스토밍 UI: React·ReactDOM CDN
- 사용자·회차·팀: 제공된 PostgreSQL VIEW 읽기 전용 조회
- 협업 갱신: HTTP polling + version 충돌 검사
- 백그라운드 작업: PostgreSQL 작업 테이블 + Django management command worker

부모 프로젝트의 테스트용 `ideas` 앱은 확정 구현이 아닙니다. 이 저장소에서는 독립 시스템을 완성하며, 부모 프로젝트 이식은 부모 운영 팀이 담당합니다.

## 처음 시작하기

처음 참여한다면 아래 문서를 순서대로 읽으세요.

1. [프로젝트 시작 안내](docs/00_START_HERE.md)
2. [개발 환경 설치](docs/01_LOCAL_SETUP.md)
3. [Git과 GitHub 작업 흐름](docs/02_GIT_WORKFLOW.md)
4. [브랜치·커밋·Pull Request](docs/03_BRANCH_COMMIT_PR.md)
5. [프로젝트 구조](docs/04_PROJECT_STRUCTURE.md)
6. [팀 코드 분배표](docs/05_TEAM_TASKS.md)
7. [문제 해결](docs/06_TROUBLESHOOTING.md)
8. [AI 코딩 규칙](docs/07_AI_CODING_RULES.md)
9. [부모 팀 이관 메모](docs/08_PARENT_HANDOFF.md)
10. [코드 전달 양식](docs/09_CODE_DISTRIBUTION_TEMPLATE.md)
11. [저장소 관리자 설정](docs/10_REPOSITORY_OWNER_SETUP.md)

## 가장 중요한 규칙

- `main`에서 직접 작업하거나 push하지 않습니다.
- 작업 하나마다 새 브랜치를 만듭니다.
- 작은 단위로 commit하고 GitHub에 push합니다.
- Pull Request(PR)를 열고 팀원 한 명의 확인을 받은 뒤 merge합니다.
- `.env`, 비밀번호, API 키, 실제 사용자 데이터는 절대 commit하지 않습니다.
- 다른 사람 파일을 임의로 덮어쓰지 않습니다.

## 현재 상태

초기 저장소에는 협업 문서와 실제 프로젝트의 빈 폴더 구조만 있습니다. 팀원은 팀장에게 받은 정확한 파일 경로와 코드를 해당 폴더에 새 파일로 추가한 뒤 commit·push합니다.
