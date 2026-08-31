# 아이디어 디벨로퍼 홈 백엔드 시나리오

이 문서는 홈 UI/UX 목업을 기준으로 홈 화면 조회, KPI, PRD 목록, 카드 표시, 필터, 상세 화면 이동에 필요한 백엔드 규칙을 통일한 문서다.

첨부 자료는 화면과 현재 목업 동작을 확인하는 참고 자료로만 사용했다. 첨부 자료 안의 제안이나 지시는 사용자 요구사항으로 간주하지 않았다.

## 1. 홈 화면 조회 범위

홈 화면에는 로그인한 사용자가 열람 권한을 가진 PRD만 보여준다.

- 본인이 만든 PRD
- 본인이 참여자로 등록된 PRD
- 본인이 속한 팀에 공유된 PRD
- 별도로 열람 권한을 받은 PRD

권한이 없거나 소프트 삭제된 PRD는 KPI와 목록에서 모두 제외한다. 홈 화면의 모든 개수와 평균은 같은 조회 범위를 사용해야 한다.

`전체 PRD`와 목록의 전체 탭이 서로 다른 범위를 사용하지 않도록, 서버에서 공통 조회 조건을 한 번 정의해 재사용한다.

### 부모 시스템과 실행 모드

아이디어 디벨로퍼는 우리 팀이 독립 Django 시스템으로 완성해 전달하는 프로젝트다. 부모 시스템으로 실제 이식하는 작업은 부모 프로젝트 운영 팀이 담당한다. 우리 구현 범위는 단독 실행 가능한 시스템이며, 이식하기 쉽도록 스택·외부 식별자·VIEW 조회 규격·URL namespace·템플릿 계약을 맞춘다.

- Backend: Django
- UI: Bootstrap
- Database: PostgreSQL
- 우리 팀 납품 범위: 독립 Django 프로젝트
- 부모 이식 후 목표: 부모 Django 프로젝트의 앱과 URL namespace로 동작

### 부모 저장소 확인 결과와 적용 기준

2026-08-31 기준 부모 저장소 `KANT-2/review-system`의 실제 구성을 확인했다. 저장소 안의 `ideas` 앱은 팀 테스트용 임시 구현이므로 제품 요구사항의 확정 근거로 사용하지 않는다. 부모 저장소를 직접 수정하거나 그 구현에 의존하지 않고, 호환 가능한 독립 시스템을 만드는 참고 자료로만 사용한다.

- Django: `5.2.x`
- Bootstrap: CDN `5.3.2`
- Bootstrap Icons: CDN `1.11.2`
- Database: PostgreSQL, 개발 환경 일부는 SQLite fallback
- 사용자 모델: `accounts.User`, `AUTH_USER_MODEL = "accounts.User"`
- 사용자 역할: `student`, `tutor`, `admin`
- 세션: Django DB session, `HttpOnly`, `SameSite=Lax`
- 템플릿: `templates/base.html`
- 확장 블록: `extra_head`, `breadcrumb`, `content`, `modals`, `extra_js`
- 통합 URL: `/ideas/`, namespace `ideas`
- 회차: `rounds.EvaluationRound`
- 회차 참가자: `rounds.RoundParticipant`
- 팀과 소속: `teams.Team`, `teams.TeamMembership`

부모 저장소에는 현재 Redis, Celery, Django Channels, Redis Channel Layer가 설치되어 있지 않다. WSGI 중심 구성이고 ASGI 파일도 일반 HTTP Django 앱만 올린다. 따라서 이들을 기존 인프라로 가정하거나 0단계에서 자동 추가하지 않는다.

현재 운영 패턴은 다음과 같다.

- 예약 작업: PostgreSQL에 작업 상태를 저장하고 Django management command를 별도 scheduler 컨테이너가 60초마다 실행
- 화면 갱신: 알림 기능에서 HTTP polling 사용
- 캐시: 별도 Redis 캐시 없음
- 실시간 WebSocket: 없음

아이디어 디벨로퍼 MVP도 먼저 이 운영 패턴에 맞춘다. Redis·Celery·Channels가 꼭 필요한 기능은 부모 팀이 이식할 때 추가 도입을 판단할 수 있도록 별도 선택사항으로 문서화하되, 우리 단독 시스템의 필수 의존성으로 만들지 않는다.

현재 React/Tailwind 기반 화면 코드는 Figma UI/UX 목업으로 취급한다. 홈, PRD 작성, 상세 화면은 독립 시스템의 Django template과 Bootstrap으로 구현하되, 부모가 쉽게 옮길 수 있도록 Bootstrap 버전과 template block 이름을 부모 규격에 맞춘다.

브레인스토밍 화면만 기술적 이유로 React를 CDN 방식으로 사용한다. 독립 시스템의 Django template과 Bootstrap 화면 안에 React mount 영역을 두고, 브레인스토밍 JavaScript만 React가 담당한다. Tailwind 런타임은 추가하지 않고 Bootstrap과 앱 전용 CSS를 사용한다.

React와 ReactDOM CDN 버전은 명시적으로 고정하고, 부모 시스템의 CSP와 정적 파일 정책에 맞춰 허용한다. CDN 장애 시 브레인스토밍 진입 오류를 안내하되 홈과 PRD 기본 기능에는 영향을 주지 않도록 분리한다.

부모 이식을 위해 비즈니스 로직을 두 벌로 만들지 않는다. 독립 시스템에서 로그인 사용자와 현재 회차를 구하는 부분만 `IntegrationContextResolver` 같은 어댑터로 분리하고, 부모 팀이 이 어댑터만 교체할 수 있게 한다.

```text
IntegrationContext
- user_id
- round_id
- participant_id
- team_id
- user_role
- is_staff
- is_superuser
```

단독 시스템에서는 자체 Django 로그인 또는 개발·테스트 인증 어댑터로 `request.user`를 만들고, VIEW의 `user_id`와 연결한다. 운영용 외부 ID와 로컬 PK를 혼동하지 않도록 매핑을 분리한다. 부모 팀이 이식할 때는 부모의 인증된 `request.user`를 사용하도록 resolver만 교체한다. VIEW는 어느 모드에서도 로그인 세션을 대신하지 않는다.

현재 회차는 VIEW에서 회차 상태와 사용자 참가 정보를 조회해 결정한다. 진행 중 회차가 하나면 기본 선택하고, 없으면 회차 없음 화면, 여러 개면 회차 선택 화면을 제공한다. 부모 저장소는 진행 중 회차를 하나로 제한하지만 독립 시스템이 그 내부 DB 제약에 직접 의존하지 않도록 한다.

### 공통 PostgreSQL VIEW

사용자와 회차별 팀 소속은 부모 시스템이 제공하는 읽기 전용 VIEW를 사용한다.

- `public.ax_user_team_login_view`: 사용자 기본 정보와 대표 회차·팀 정보
- `public.user_round_team_view`: 사용자별 회차·팀 소속 이력

원본 `accounts_user`, `rounds_*`, `teams_*` 테이블을 자식 시스템이 직접 JOIN하지 않는다. VIEW에 INSERT, UPDATE, DELETE하지 않는다.

단독 시스템의 인증 여부와 세션 만료 판정은 자체 Django `request.user`로 처리한다. VIEW는 사용자 표시 정보, 회차 참가 여부, 회차별 팀 소속을 조회하는 읽기 전용 연동 계층이다. 부모 이식 후에는 부모 팀이 인증 resolver를 부모 `request.user`로 연결한다.

회차별 접근 권한과 팀 정보는 반드시 `user_id + round_id`로 조회한다. `ax_user_team_login_view`의 대표 팀만 보고 현재 회차의 팀이라고 판단하지 않는다.

```sql
SELECT *
FROM public.user_round_team_view
WHERE user_id = :user_id
  AND round_id = :round_id;
```

자식 시스템의 PRD에는 최소한 다음 외부 식별자를 저장한다.

- `round_id`
- `team_id`
- 생성자의 `user_id`

VIEW는 읽기 전용이며 자식 테이블과 DB FK를 강제하기 어려울 수 있으므로, 저장 전에 연동 서비스가 VIEW에서 유효성을 검증한다. 외부 ID를 저장한 뒤에도 모든 조회에서 현재 사용자의 회차·팀 소속과 PRD 권한을 다시 확인한다.

### 단독 시스템 로그인

단독 시스템은 로그인 화면과 로그아웃 기능을 제공한다. 회원가입, 비밀번호 설정, 비밀번호 찾기, 사용자 프로필 수정은 제공하지 않는다. 사용자 원본은 이미 부모 DB에 있으므로 우리 시스템이 별도의 회원 원장을 만들지 않는다.

두 VIEW에는 비밀번호나 인증 토큰이 없으므로 VIEW 조회만으로 사용자를 로그인시키지 않는다. `user_id`를 입력하게 하거나 이름 목록에서 사용자를 고르는 방식은 운영 환경에서 금지한다.

MVP 로그인은 이메일 일회용 인증번호 방식으로 구현한다.

1. 사용자가 이메일을 입력한다.
2. 서버는 이메일을 소문자·공백 제거 형태로 정규화한다.
3. `ax_user_team_login_view`에서 `user_email` 또는 `primary_email`이 일치하고 `is_active = true`, `approval_status = approved`인 사용자를 찾는다.
4. 조건에 맞으면 6자리 일회용 코드를 이메일로 보낸다.
5. 사용자가 유효 시간 안에 코드를 맞히면 Django 세션을 만들고 외부 `user_id`를 세션의 로그인 신원에 연결한다.
6. 이후 모든 요청은 세션 사용자와 VIEW의 외부 `user_id`를 대조한다.

Django 세션 연동을 위해 최소한의 로컬 사용자 매핑 모델은 둘 수 있다. 이 모델은 회원 원장이 아니라 인증 세션용 어댑터다.

- `external_user_id`: unique, VIEW의 `user_id`
- `email_snapshot`: 표시·감사용 스냅샷
- `is_active`: 로컬 세션 차단용
- `last_verified_at`: 마지막 VIEW 검증 시각
- 비밀번호: 사용 불가 상태로 저장

이름, 역할, 팀, 회차, 프로필은 로컬 사용자 모델을 진실의 원천으로 사용하지 않고 VIEW에서 읽는다. 로그인과 중요 쓰기 요청 전에 VIEW의 활성·승인 상태를 다시 확인한다.

계정 존재 여부가 노출되지 않도록 등록되지 않은 이메일에도 화면에는 같은 안내 문구를 보여준다. 인증번호는 원문으로 저장하지 않고 해시로 저장하며, 기본 만료 시간 10분, 1회 사용, 최대 입력 실패 5회, 재발송 대기 60초, 이메일·IP별 요청 횟수 제한을 둔다.

로그인 성공 시 VIEW의 `last_login`을 수정하지 않는다. VIEW는 읽기 전용이므로 우리 시스템의 로그인 감사 로그에 성공·실패 시각, 외부 `user_id`, IP와 user-agent 요약을 기록한다. 로그에는 인증번호 원문을 남기지 않는다.

로컬 개발과 자동 테스트에서는 `DEBUG = true`일 때만 사용자 선택형 테스트 로그인을 허용할 수 있다. 운영 설정에서 해당 URL이 등록되거나 동작하면 배포 검사가 실패해야 한다.

로그인 프론트도 독립 시스템 구현 범위에 포함한다.

- 1단계 화면: 이메일 입력과 `인증번호 받기`
- 2단계 화면: 마스킹한 수신 이메일, 6자리 인증번호 입력, 남은 시간, 재전송 버튼
- 공통 상태: 전송 중, 검증 중, 만료, 잘못된 코드, 횟수 초과, 네트워크 오류
- 성공: 안전한 `next` 경로가 있으면 그 경로, 없으면 아이디어 홈으로 이동
- 보안: CSRF 적용, open redirect 차단, 계정 존재 여부를 드러내지 않는 동일 문구
- 접근성: 이메일 `autocomplete=email`, 인증번호 `autocomplete=one-time-code`, 숫자 키패드, 키보드 포커스, 오류 안내 연결

`DEBUG = true`에서만 별도 테스트 로그인 화면을 제공한다. VIEW의 활성·승인 사용자 일부를 서버 검색으로 조회해 선택하고 로그인할 수 있게 하되, 전체 사용자 데이터를 한 번에 브라우저로 내려보내지 않는다. 화면 상단에 `개발 전용` 표시를 하고 운영 환경에서는 URL, view, template 진입이 모두 차단되어야 한다.

부모 팀이 이식한 뒤에는 이 독립 로그인 화면을 비활성화하고 부모 Django 세션의 `request.user`를 사용하도록 인증 resolver를 교체할 수 있다. PRD·브레인스토밍 비즈니스 로직은 바꾸지 않는다.

## 2. PRD 상태

PRD 상태는 `status` 하나만 사용한다.

- `in_progress`: 작성 중
- `completed`: 완료
- `held`: 보류
- `dropped`: 드랍

`is_held`, `pending`, `hold`, `holding`, `is_completed`처럼 같은 의미를 나타내는 PRD 상태 필드를 따로 만들지 않는다.

기존 데이터에 `홀드`, `홀딩`, `보류`가 섞여 있다면 모두 `held`로 변환한다. 화면에는 `보류`로 통일해 표시한다.

질문 항목의 완료 여부를 나타내는 `is_completed`는 PRD 상태가 아니라 완성도 계산용 값이므로 유지할 수 있다.

## 3. PRD 유형과 뱃지

PRD 유형은 `prd_type` 하나로 구분한다.

- `new_product`: 신규 프로젝트
- `new_feature`: 신규 기능
- `improvement`: 기능 개선

유형 뱃지는 PRD가 생성된 날짜와 관계없이 항상 `prd_type`에 따라 표시한다.

`NEW` 뱃지는 유형 뱃지와 별개다. 생성 시각부터 72시간 동안만 표시한다.

```text
show_new_badge = now < created_at + 72 hours
```

회의에서 확정한 3일 기준을 사용한다. 별도의 7일짜리 신규 뱃지는 만들지 않는다.

## 4. 사용자 인사와 새 PRD 만들기

상단 인사에는 현재 회차 기준 로그인 사용자의 표시 이름을 사용한다.

- 사용자 이름 우선순위: `display_name_snapshot` -> `first_name + last_name` -> `primary_email`
- 진행 중 PRD 수: 홈 조회 범위 중 `status = in_progress`인 PRD 개수

`새 PRD 만들기`를 누르면 PRD 생성 화면으로 이동한다. 생성 화면에서는 PRD 유형을 선택한 뒤 기본 정보를 입력한다.

MVP에서는 세부 유형을 별도 단계로 두지 않는다.

```text
유형 선택 -> 기본 정보 -> PRD 생성
```

기본 정보에는 제목, 한 줄 소개, 목표 마감일, 참여자를 포함한다. 제목은 유형과 관계없이 `PRDs.title`에 저장한다.

### 참여자 선택

참여자 선택 영역에는 `현재 내가 속한 팀`과 `개별 추가`를 제공한다.

- `현재 내가 속한 팀`에는 로그인 사용자가 현재 회차에 속한 팀만 반환한다.
- 팀원 모두 추가를 누르면 해당 팀의 활성 사용자 전체를 참여자 후보로 추가한다.
- 로그인 사용자는 PRD 소유자로 기본 선택하며 해제할 수 없다.
- 개별 추가는 `User.display_name`으로 검색한다.
- 이미 추가된 사용자는 검색 결과에 체크 상태로 표시한다.
- 같은 사용자를 팀 추가와 개별 추가로 중복 등록하지 않는다.
- 검색 결과가 없으면 빈 배열과 `일치하는 사용자가 없습니다` 상태를 반환한다.
- 역할은 기본 목록에서 표시하지 않는다.
- 동명이인이 있을 때만 이메일과 소속 팀 등 최소 식별 정보를 함께 반환한다.

팀원 검색은 전체 사용자 정보를 내려받아 프론트에서 찾지 않고 서버 검색 API를 사용한다. 기본 검색 범위는 현재 회차 참가자이며, 필요하면 현재 팀으로 추가 제한한다.

```http
GET /api/users/search?q=김지수&round_id=3&exclude_prd_id=123
```

검색어 앞뒤 공백을 제거하고 최소 검색 길이와 페이지 크기 제한을 둔다. 검색 결과에는 사용자 ID, 표시 이름, 선택 여부, 동명이인 구분에 필요한 최소 정보만 포함한다.

PRD 생성 요청의 참여자 ID는 서버에서 다시 검증한다. 존재하지 않거나 비활성화된 사용자, 초대 권한이 없는 사용자, 중복 ID는 그대로 저장하지 않는다.

참여자 검증은 `user_round_team_view`의 `participant_id`, `round_id`, `team_id`를 기준으로 한다. 사용자 ID만 존재한다고 해서 현재 회차 참여자로 인정하지 않는다.

초대가 필요한 방식이라면 참여자를 즉시 확정하지 않고 `pending` 초대 관계를 만들고 대시보드 알림을 보낸다. 이미 참여 중이거나 같은 초대가 대기 중이면 새 초대를 중복 생성하지 않는다.

## 5. 상단 KPI

홈 KPI는 다음 기준으로 계산한다.

### 전체 PRD

홈 조회 범위에 포함되는 소프트 삭제되지 않은 PRD의 전체 개수다. `in_progress`, `completed`, `held`, `dropped` 상태를 모두 포함한다.

### 진행 중

`status = in_progress`인 PRD 개수다.

### 평균 완성도

홈 조회 범위에 포함되는 전체 PRD의 `completion_rate` 산술 평균이다.

```text
average_completion_rate = round(sum(completion_rate) / PRD count)
```

PRD가 하나도 없으면 `0%`를 반환한다. `completionScore`, `progress`처럼 같은 의미의 별도 계산값을 두지 않고 `completion_rate` 하나를 사용한다.

### 완료됨

`status = completed`인 PRD 개수다.

### AI 코칭 횟수

시스템 프롬프트 정의를 저장하는 `AI_Prompts` 행 개수가 아니라, 실제 호출 기록인 `AI_Usage_Logs`를 집계한다.

`feature_type = COACHING`인 성공한 호출만 센다. 초안 생성 호출도 같은 `feature_type`으로 저장 중이라면 대화형 코칭과 구분할 수 없으므로, `action_type = chat | draft`를 추가한 뒤 홈 KPI에는 `chat`만 포함한다.

집계 기간을 화면에 표시하지 않는 현재 목업에서는 해당 사용자가 접근 가능한 PRD의 누적 코칭 호출 수를 반환한다.

### 이번 주 마감

오늘을 포함해 앞으로 7일 이내 마감되는 PRD 개수다.

```text
today <= deadline < today + 7 days
```

이미 마감일이 지난 PRD, `completed`, `dropped` 상태의 PRD는 제외한다. 날짜 계산은 사용자 타임존 기준 날짜로 처리한다.

## 6. KPI 카드 클릭과 자동 필터

상단 KPI 카드를 누르면 해당 조건을 PRD 목록에 바로 적용한다.

- 전체 PRD: 상태와 마감 필터 초기화
- 진행 중: `status = in_progress`
- 평균 완성도: 기본 동작은 필터가 아니라 `completion_rate` 내림차순 정렬
- 완료됨: `status = completed`
- AI 코칭 횟수: 기본 동작은 `ai_coaching_count` 내림차순 정렬
- 이번 주 마감: `deadline_from = today`, `deadline_to = today + 6 days`, 마감 임박순 정렬

같은 KPI 카드를 다시 누르면 해당 빠른 필터를 해제한다. 탭 조건은 유지하고 KPI가 적용한 상태·정렬·마감 조건만 해제한다.

## 7. PRD 목록 탭

탭은 서로 다른 페이지가 아니라 동일한 목록 API의 조회 조건이다.

- `전체`: 접근 가능한 모든 PRD
- `프로젝트`: `prd_type = new_product`
- `팀`: 참여자가 2명 이상이거나 팀 공유로 생성된 PRD
- `개인`: 참여자가 로그인 사용자 한 명뿐인 PRD

`팀`과 `개인`은 `members.length`를 프론트에서 세어 판단하지 않고, 서버가 참여자 관계를 기준으로 필터링한다.

`프로젝트`라는 이름은 `신규 프로젝트` 유형과 의미가 같아야 한다. 사용자가 팀별 그룹 보기를 의도한 것이라면 탭 이름과 규칙을 다시 정해야 하므로 현재는 목업 코드의 `new_product` 필터를 따른다.

전체 탭의 기본 정렬은 다음 순서다.

1. 상태: 작성 중 -> 완료 -> 보류 -> 드랍
2. 같은 상태에서는 최근 수정일 내림차순

## 8. 필터와 정렬

목록은 다음 필터를 지원한다.

- 상태: 작성 중 / 완료 / 보류 / 드랍
- PRD 유형: 신규 프로젝트 / 신규 기능 / 기능 개선
- 목표 마감일 범위
- 참여자
- 팀

보류 여부는 `is_held`로 따로 필터링하지 않고 `status = held`를 사용한다.

다음 정렬을 지원한다.

- 기본 정렬
- 마감 임박순
- 완성도 높은순
- 최근 수정순
- AI 코칭 많은순

여러 상태를 선택하면 OR 조건으로 처리하고, 상태·유형·마감일·참여자처럼 종류가 다른 필터끼리는 AND 조건으로 처리한다.

네 가지 상태를 모두 선택하면 상태 필터가 없는 것과 같은 결과를 반환한다.

## 9. PRD 카드

목록 API는 카드에 필요한 값을 한 번에 반환한다.

- `id`
- `title`
- `description`
- `prd_type`
- `status`
- `show_new_badge`
- `completion_rate`
- `deadline`
- `d_day`
- `updated_at`
- `participants`
- `participant_count`
- `ai_coaching_count`

프론트가 질문 전체, AI 로그 전체, 참여자 전체를 각각 추가 조회해 카드 값을 계산하지 않도록 한다.

프로젝트 설명은 별도 필드인 `PRDs.description`에 저장한다. 현재 테이블에 없다면 nullable 필드로 추가하고, 기존 데이터는 빈 문자열로 처리한다.

## 10. 완성도와 Progress Bar

완성도는 PRD 질문 항목의 완료 체크를 기준으로 서버에서 계산한다.

```text
completion_rate = completed active questions / all active questions * 100
```

- 소프트 삭제된 질문은 분모와 분자에서 제외한다.
- 보류된 질문은 정상 데이터이므로 분모에 포함한다.
- 질문이 하나도 없으면 `0%`다.
- 결과는 0부터 100 사이의 정수로 반올림한다.

프론트는 서버가 반환한 `completion_rate`로 숫자와 Progress Bar를 함께 그린다. 숫자와 바가 서로 다른 필드를 사용하지 않는다.

PRD를 `completed`로 바꿀 수 있는 조건은 별도 정책으로 둔다. MVP에서는 완료 상태 변경 시 미완료 질문이 있으면 경고하되, 권한 있는 사용자가 확인 후 완료할 수 있게 한다. 따라서 `status = completed`와 `completion_rate = 100`이 반드시 같은 뜻은 아니다.

## 11. 마감일과 D-Day

마감일은 `deadline` 날짜 하나를 사용한다. `days_left`를 DB에 중복 저장하지 않는다.

```text
d_day = deadline - today
```

- 미래: `D-n`
- 오늘: `D-Day`
- 과거: `D+n`
- 마감일 없음: `null`

D-Day, 이번 주 마감 KPI, 마감 임박순 정렬은 모두 같은 `deadline`과 사용자 타임존을 사용한다.

## 12. 참여자 Avatar와 공유 권한

참여자는 `target_user_id` 하나를 PRD에 직접 넣는 방식이 아니라 PRD와 사용자의 다대다 관계로 관리한다.

예시 필드:

- `prd_id`
- `user_id`
- `role`: `owner | editor | viewer`
- `created_at`

Avatar에는 사용자의 표시 이름 첫 글자를 사용한다. 이름이 비어 있으면 이메일 첫 글자 등 공통 폴백 규칙을 사용한다.

카드에는 최대 4명만 내려주고, 나머지는 `participant_count - 4`로 표시할 수 있다.

공유 권한은 카드에 항상 노출하지 않아도 된다. 다만 상세 화면 진입과 수정 버튼 제어를 위해 목록 응답에 현재 사용자의 `my_role`과 `can_edit`은 포함한다.

## 13. 최근 수정일

최근 수정일은 질문의 `is_completed` 시각이 아니라 PRD의 실제 변경 시각을 사용한다.

다음 변경이 발생하면 `PRDs.updated_at`을 갱신한다.

- PRD 기본 정보 수정
- 질문 답변 저장 또는 완료 체크 변경
- 섹션 변경
- 댓글 생성·수정·삭제
- 참여자 또는 공유 권한 변경
- AI 결과를 PRD에 반영

단순 조회와 AI에게 질문만 한 행위는 PRD 내용 변경이 아니므로 `updated_at`을 갱신하지 않는다.

## 14. PRD 카드 클릭과 상세 화면

카드를 누르면 PRD ID를 사용해 상세 화면으로 이동한다.

상세 API에서는 다시 로그인과 PRD 접근 권한을 확인한다. 목록에서 보였다는 사실만으로 권한 검사를 생략하지 않는다.

상세 화면은 다음 데이터를 탭 또는 구역별로 조회할 수 있다.

- PRD 기본 정보
- PRD 섹션과 질문 항목
- 질문별 답변
- 댓글
- 참여자와 공유 권한
- AI 사용 기록
- AI 채팅 내역
- 수정 이력

초기 진입 속도를 위해 기본 정보와 섹션·질문만 먼저 내려주고, 댓글·AI 기록·수정 이력은 사용자가 해당 영역을 열 때 페이지네이션으로 조회한다.

## 15. AI 사용 기록

AI 사용 횟수는 실제 AI 호출마다 `AI_Usage_Logs`에 한 행씩 저장한다.

권장 필드:

- `user_id`
- `prd_id`
- `feature_type`
- `action_type`
- `status`: `success | failed | cancelled`
- `total_tokens`
- `created_at`

홈 KPI에는 `status = success`, `feature_type = COACHING`, `action_type = chat`만 포함한다.

AI 대화 내용은 `AI_Chat_Histories`에서 관리한다. 프롬프트 정의를 저장하는 `AI_Prompts`는 사용 횟수 집계에 사용하지 않는다.

## 16. 홈 API

홈 진입 시 KPI와 첫 페이지 목록을 한 요청으로 받을 수 있다.

```http
GET /api/home?tab=all&status=in_progress&sort=updated_desc&page=1&page_size=12
```

응답 예시:

```json
{
  "user": {
    "id": 17,
    "display_name": "김지수"
  },
  "kpis": {
    "total_prds": 9,
    "in_progress_prds": 5,
    "average_completion_rate": 62,
    "completed_prds": 4,
    "ai_coaching_count": 59,
    "due_this_week": 1
  },
  "applied_filters": {
    "tab": "all",
    "statuses": ["in_progress"],
    "sort": "updated_desc"
  },
  "items": [],
  "pagination": {
    "page": 1,
    "page_size": 12,
    "total_items": 5,
    "total_pages": 1
  }
}
```

KPI는 현재 목록 필터 결과가 아니라 사용자의 전체 홈 조회 범위를 기준으로 반환한다. 그래야 필터를 적용해도 KPI 숫자가 바뀌지 않고, KPI 카드가 안정적인 빠른 필터 역할을 한다.

## 17. 빈 화면과 오류

사용자에게 PRD가 하나도 없으면 KPI는 모두 0을 반환하고 새 PRD 만들기 안내를 보여준다.

필터 결과만 비어 있으면 전체 데이터가 없는 것으로 처리하지 않는다. 적용된 필터를 함께 반환하고 필터 초기화 또는 새 PRD 만들기를 안내한다.

권한이 없는 PRD 상세 요청에는 `403 Forbidden`, 존재하지 않거나 삭제된 PRD에는 `404 Not Found`를 반환한다. 목록 조회 중 일부 데이터가 잘못됐다고 해서 권한 없는 PRD를 임시로 노출하지 않는다.

## 18. 성능과 인덱스

홈 목록에서 사용할 조건에 맞춰 다음 인덱스를 검토한다.

- `PRDs(status, updated_at)`
- `PRDs(prd_type, updated_at)`
- `PRDs(deadline)`
- `PRDParticipants(user_id, prd_id)`
- `AIUsageLogs(prd_id, feature_type, action_type, status)`

KPI 때문에 PRD마다 질문과 AI 로그를 반복 조회하지 않는다. 완성도와 AI 횟수는 집계 쿼리, 서브쿼리 또는 갱신 가능한 집계 필드로 한 번에 계산한다.

집계 필드를 저장한다면 질문 완료 체크나 AI 로그 생성과 같은 원본 데이터 변경과 같은 트랜잭션에서 갱신하거나, 재계산 작업으로 불일치를 복구할 수 있어야 한다.

## 19. 인수 조건

- 로그인 사용자가 접근할 수 없는 PRD는 KPI와 목록에 포함되지 않는다.
- `홀드`, `홀딩`, `보류`가 별도 상태로 생성되지 않고 모두 `held`로 처리된다.
- 생성 후 72시간이 지나면 `NEW` 뱃지가 자동으로 사라진다.
- 유형 뱃지는 생성일과 관계없이 `prd_type`에 따라 계속 표시된다.
- 진행 중 KPI를 누르면 목록에 `in_progress` 필터가 적용되고, 다시 누르면 해제된다.
- 이번 주 마감 KPI에는 오늘부터 6일 뒤까지의 미완료·미드랍 PRD만 포함된다.
- 질문 완료 여부가 바뀌면 카드 완성도와 평균 완성도가 같은 계산 기준으로 갱신된다.
- AI 프롬프트 정의를 추가해도 AI 코칭 횟수는 증가하지 않는다.
- 실패하거나 취소된 AI 요청은 홈의 AI 코칭 횟수에 포함되지 않는다.
- 카드와 상세 화면 모두에서 PRD 권한을 검사한다.
- 마감일, D-Day, 이번 주 마감, 마감 임박순 정렬이 같은 날짜 기준을 사용한다.
- 최근 수정일은 질문 완료 시각이 아니라 PRD 내용의 실제 최종 변경 시각을 사용한다.

## 20. 추가 결정이 필요한 사항

다음 항목은 현재 자료만으로 확정하지 않는다.

- `프로젝트` 탭이 `신규 프로젝트` 유형을 뜻하는지, 프로젝트별 그룹 보기를 뜻하는지
- `completed` 변경을 완성도 100%에서만 허용할지
- 완료·드랍 PRD의 지난 마감일을 카드에 계속 표시할지
- AI 코칭 KPI의 기간을 누적으로 둘지, 이번 주 또는 이번 달로 제한할지
- 공유 권한 뱃지를 홈 카드에 실제로 노출할지
- 최근 활동과 이번 주 활동을 MVP 홈 범위에 포함할지

결정 전에는 임의의 필드나 상태값을 추가하지 않는다.

## 21. 꼭 지킬 원칙

- 홈과 상세의 모든 API에서 로그인과 PRD 권한을 확인한다.
- PRD 상태는 `status` 하나만 사용한다.
- PRD 유형과 `NEW` 뱃지는 서로 다른 개념이다.
- `NEW` 뱃지는 생성 후 72시간만 표시한다.
- 완성도 숫자와 Progress Bar는 같은 `completion_rate`를 사용한다.
- `days_left`를 저장하지 않고 `deadline`으로 D-Day를 계산한다.
- 최근 수정일은 `updated_at`을 사용한다.
- 참여자는 PRD와 사용자의 관계 테이블로 관리한다.
- AI 코칭 횟수는 `AI_Usage_Logs`에서 계산한다.
- 프롬프트 정의 테이블인 `AI_Prompts`를 사용량 집계에 사용하지 않는다.
- 결정되지 않은 기능은 임의로 확정 구현하지 않는다.

## 22. UI/UX 변경사항 반영 점검

첨부 홈 UI/UX 변경사항과 이 시나리오의 반영 상태는 다음과 같다.

### 반영 완료

- 새 PRD 만들기 진입
- 세부 유형 단계를 제거한 `유형 선택 -> 기본 정보` 흐름
- 세 유형을 `new_product`, `new_feature`, `improvement`로 구분
- 유형과 관계없이 제목을 `PRDs.title`에 저장
- 마감일을 D-Day, 이번 주 마감, 정렬·필터에 공통 사용
- 현재 소속 팀 조회와 팀원 모두 추가
- 사용자 이름 검색과 검색 결과 없음 처리
- 본인 기본 선택 및 해제 방지
- 참여자 중복 등록 방지
- KPI 카드 클릭 시 자동 필터 또는 정렬 적용
- `NEW` 뱃지 3일 노출

### 프론트 구현 항목이므로 백엔드 시나리오에서 제외

- 날짜 입력 칸 전체를 눌러 캘린더 활성화
- 캘린더 아이콘 중복 제거
- 카드 제목을 행동형 문구로 변경
- 입력창, 팝오버, 체크 표시의 세부 배치와 스타일

백엔드는 날짜 형식과 필수 여부만 검증하고, 입력 칸 클릭 범위나 아이콘 개수는 제어하지 않는다.

### 별도 결정 필요

- 참여자를 즉시 추가할지 초대 수락 후 참여자로 확정할지
- 팀원 모두 추가 시 비활성 계정과 외부 게스트를 포함할지
- 동명이인 식별 정보로 이메일 전체를 보여줄지 일부 마스킹할지
- 초대 알림을 앱 내부 알림만 보낼지 이메일도 보낼지

## 23. 홈과 PRD 생성 예외 상황

### 사용자 이름이나 팀 정보가 없는 경우

표시 이름이 없으면 정해진 폴백 이름을 사용한다. 소속 팀이 없으면 팀 영역은 빈 상태로 표시하되 개별 사용자 검색은 계속 사용할 수 있다.

### 팀원 모두 추가 중 구성원이 바뀐 경우

화면을 연 뒤 팀원이 탈퇴했을 수 있으므로 PRD 생성 시 서버가 팀 구성원을 다시 확인한다. 더 이상 유효하지 않은 사용자는 제외하고 제외된 사용자 목록을 알려준다.

### 같은 사용자를 여러 경로로 추가한 경우

팀원 모두 추가, 개별 검색, 재시도 요청에서 같은 사용자 ID가 반복돼도 참여 관계는 하나만 만든다. DB에도 `(prd_id, user_id)` 유니크 제약을 둔다.

### 동명이인이 있는 경우

이름만으로 자동 선택하지 않는다. 사용자 ID를 기준으로 저장하고, 화면에는 이메일 일부와 현재 소속 팀을 함께 보여 사용자가 직접 구분하게 한다.

### 마감일이 잘못된 경우

유효하지 않은 날짜 형식은 `400 Bad Request`를 반환한다. 과거 날짜 허용 여부는 정책으로 결정하되, 허용한다면 생성 직후 `D+n`으로 표시될 수 있음을 안내한다.

### KPI와 목록 숫자가 잠시 다른 경우

질문 완료, 상태 변경, AI 사용 로그가 동시에 갱신될 수 있다. 변경 이벤트 수신 후 해당 값을 낙관적으로 더하기만 하지 말고 홈 KPI를 다시 조회해 실제 집계값과 맞춘다.

### 필터 결과가 없는 경우

전체 PRD가 없는 상태와 필터 결과만 없는 상태를 구분한다. 필터 결과만 비었으면 현재 필터와 초기화 동작을 제공한다.

### KPI 카드를 연속으로 누른 경우

마지막 사용자 선택을 기준으로 필터 상태를 한 번만 적용한다. 이전 요청의 응답이 늦게 도착해 최신 필터 결과를 덮어쓰지 않도록 요청 ID 또는 취소 처리를 사용한다.

### PRD 생성 요청이 중복된 경우

네트워크 재시도로 같은 PRD가 여러 개 생기지 않도록 생성 요청에 idempotency key를 사용한다. 같은 키가 다시 오면 첫 번째 생성 결과를 반환한다.

### 초대 알림 전송에 실패한 경우

PRD 생성 자체와 알림 전송을 분리한다. PRD와 참여 관계 저장이 성공했다면 생성 요청을 실패로 되돌리지 않는다. MVP에서는 부모 시스템과 같은 PostgreSQL 작업 테이블과 Django management command scheduler로 알림을 재시도한다. Celery를 도입하기 전에는 이를 Celery 작업 큐라고 표현하지 않는다.

### 부모 탭에서 회차 정보가 전달되지 않은 경우

임의로 최신 회차를 선택하지 않는다. 단독 모드라면 회차 선택 화면을 보여주고, 통합 모드라면 부모 시스템에 회차 선택 또는 재진입을 요청한다.

### 전달된 회차에 사용자가 참여하지 않은 경우

`user_round_team_view`에서 `user_id + round_id` 조합을 찾지 못하면 `403 Forbidden`을 반환한다. URL의 `team_id`나 `round_id`만 신뢰하지 않는다.

### 사용자가 회차마다 다른 팀인 경우

현재 `round_id`에 해당하는 팀만 사용한다. 다른 회차의 팀 PRD나 참여자를 현재 홈에 섞지 않는다.

### 부모 VIEW를 조회할 수 없는 경우

통합 모드에서는 사용자·권한을 추측하거나 캐시된 값만으로 쓰기 작업을 허용하지 않는다. 읽기 전용 화면 또는 일시적 연동 오류를 반환하고 서버 로그에 VIEW 조회 실패를 기록한다.

### 단독 모드와 통합 모드의 사용자 ID가 다른 경우

운영 데이터에 로컬 사용자 ID를 그대로 저장하지 않는다. 단독 개발용 사용자는 부모 VIEW의 외부 `user_id`, `round_id`, `participant_id`, `team_id` 형식을 모사한 fixture를 사용한다.

## 24. 부모 시스템 통합 시 추가 결정 사항

VIEW 문서만으로는 다음 항목이 확정되지 않는다.

- 진행 중 회차 외의 과거·준비 회차 PRD에 진입할 때 사용할 URL 또는 선택 UI
- 독립 시스템에서 사용할 자체 로그인과 외부 `user_id` 매핑 방식
- 독립 시스템도 이식 호환성을 위해 namespace `ideas`, URL `/ideas/`를 사용할지
- 부모 base template은 `templates/base.html`, block은 `extra_head`, `breadcrumb`, `content`, `modals`, `extra_js`로 확인됐으나 최종 통합 시 변경될 가능성
- Bootstrap은 현재 CDN `5.3.2`, Bootstrap Icons는 `1.11.2`로 확인됐으므로 이 버전을 기준으로 고정할지
- 일반 화면에서 사용할 HTMX, Alpine.js 또는 vanilla JavaScript 방식
- 브레인스토밍 React CDN의 고정 버전, CSP 허용 도메인, 무결성 검증 방식
- 부모 이식 후 진짜 WebSocket 프레즌스·커서 공유를 위해 Redis와 Django Channels를 신규 도입할지
- 부모 이식 후 장시간 AI 작업을 위해 Celery·Redis를 신규 도입할지
- 자식 테이블을 부모의 `ax_evaluation` DB와 같은 schema에 둘지 별도 schema에 둘지
- 부모 `role`, `is_staff`, `is_superuser`를 자식의 owner/editor/tutor/viewer에 어떻게 매핑할지
- 한 회차에서 사용자가 복수 팀에 속할 수 있는지와 그 경우 현재 팀 선택 방식
- 단독 개발·테스트 환경에서 두 VIEW를 실제로 제공할지 fixture·대체 VIEW를 사용할지

이 값들은 연동 설정으로 분리하고 서비스 코드에 하드코딩하지 않는다.
