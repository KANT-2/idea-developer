# 05. 팀 코드 분배와 Git 연습 순서

## 파일별 코드 전달 방식

팀장은 AI가 만든 코드를 팀원에게 파일별로 나눠 전달합니다. 팀원이 기능을 새로 설계하는 연습이 아니라, 정확한 경로에 파일을 추가하고 Git 흐름을 익히는 방식입니다.

각 전달물에는 기준 브랜치 `develop`, 만들 브랜치, 정확한 파일 경로, 파일 전체 코드, commit 메시지, 의존 파일, 확인 명령을 포함합니다.

팀원은 미리 만들어진 폴더 안에 전달받은 파일만 추가합니다. 다른 파일을 함께 고치지 않습니다.

## 1차: 프로젝트 기반 코드

한 사람이 모두 생성하고 한 commit으로 올리지 않습니다. AI 생성 결과를 검토한 뒤 아래 파일 묶음으로 나눕니다. 각 팀원은 개인 branch에서 commit·push하고 `develop` 대상 PR을 만듭니다.

| 작업 묶음 | 권장 브랜치 | 주요 파일 |
|---|---|---|
| Django 설정 | `chore/django-scaffold` | `manage.py`, `config/*`, `requirements/*` |
| 공통 화면 | `feat/base-layout` | `templates/base.html`, 공통 CSS·JS |
| VIEW 연동 | `feat/integration-views` | `apps/integration/*` |
| 로그인 백엔드 | `feat/login-otp-backend` | accounts model/service/view/test |
| 로그인 프론트 | `feat/login-otp-ui` | login templates, CSS, JS, UI test |
| 테스트 로그인 | `feat/debug-login` | DEBUG 전용 view/template/test |

의존 순서는 `Django 설정 → VIEW 연동 → 로그인 백엔드 → 로그인 프론트`입니다. 파일별 commit은 가능하지만 `develop`에 merge하는 순서는 팀장이 관리합니다. 한 단계의 파일이 모두 모인 뒤 테스트하고 `main`에 올립니다.

## 2차: 핵심 기능

| 작업 묶음 | 권장 브랜치 |
|---|---|
| PRD 모델·권한 | `feat/prd-models` |
| PRD 질문·답변 | `feat/prd-sections` |
| 홈 KPI·필터 | `feat/home-dashboard` |
| PRD 상세 화면 | `feat/prd-detail-ui` |
| 브레인스토밍 모델 | `feat/brainstorm-models` |
| 브레인스토밍 React 화면 | `feat/brainstorm-canvas-ui` |
| polling·충돌 처리 | `feat/brainstorm-sync` |
| 코멘트·기여도 | `feat/contribution` |
| AI 작업 worker | `feat/ai-job-worker` |

## 파일 충돌을 줄이는 법

- 동시에 두 명이 `config/settings.py`를 수정하지 않습니다.
- 공통 URL 변경은 담당자 한 명이 작은 PR로 먼저 처리합니다.
- migration 번호가 겹치면 임의로 파일명을 바꾸지 말고 담당자와 상의합니다.
- HTML, CSS, JavaScript를 가능하면 서로 다른 담당자가 병렬 작업하되 DOM id와 API 계약을 먼저 적습니다.
- 큰 자동 생성 결과는 팀장이 먼저 파일 목록을 나눠 담당자를 지정합니다.
- 팀원은 폴더를 새로 설계하지 않고 이미 만들어진 위치에 파일만 추가합니다.

## 완료 기준

- 요구사항 동작
- 테스트 통과
- 비밀값 미포함
- 문서 업데이트
- PR 설명 작성
- 리뷰 1회 이상

단계의 모든 파일이 모이면 팀장이 전체 실행과 테스트를 수행하고 `develop → main` PR을 만듭니다.
