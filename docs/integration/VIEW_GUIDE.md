# AX2 통합 플랫폼 DB VIEW 제공 안내

## 1. 문서 목적

AX2 통합 플랫폼의 팀 간 데이터 연계를 위해 공통적으로 사용할 수 있는 PostgreSQL VIEW를 제공합니다.

이번 VIEW는 각 팀이 개별 테이블 구조를 직접 조회하지 않고, 통합 DB에서 필요한 사용자 및 팀 소속 정보를 일관된 형태로 조회할 수 있도록 하는 것을 목적으로 합니다.

현재 제공 VIEW는 다음 2개입니다.

| 구분 | VIEW | 주요 용도 | 사용 팀 |
|---|---|---|---|
| 1 | `ax_user_team_login_view` | 사용자 기본정보 및 대표 팀 정보 조회 | 전체 조 |
| 2 | `user_round_team_view` | 사용자의 Round별 팀 소속 조회 | 3조 |

---

## 2. DB 접속 환경

| 항목 | 값 |
|---|---|
| Database | `ax_evaluation` |
| User | `ax_evaluation` |
| Host | `10.2.16.91` |
| Port | `5432` |
| Password | 별도 전달 |

> **보안 주의:** DB Password는 GitHub, 문서 저장소, 메신저 공용 채널 등에 평문으로 기록하지 않고 별도 보안 채널을 통해 전달합니다.

PostgreSQL 접속 예시:

```bash
psql -h 10.2.16.91 -p 5432 -U ax_evaluation -d ax_evaluation
```

---

## 3. 사용자 관련 VIEW

### VIEW

`public.ax_user_team_login_view`

### 목적

전체 조에서 공통적으로 사용하는 사용자 기본정보 + Round 참가정보 + 팀 정보를 하나의 VIEW에서 조회할 수 있도록 제공합니다.

### 주요 연결 구조

```text
accounts_user
      │
      ├── account_emailaddress
      │
      └── rounds_roundparticipant
                │
                └── rounds_evaluationround
                │
                └── teams_teammembership
                           │
                           └── teams_team
```

### 제공 컬럼

| 컬럼 | 설명 |
|---|---|
| `user_id` | 사용자 ID |
| `user_email` | 사용자 이메일 |
| `first_name` | 이름 |
| `last_name` | 성 |
| `role` | 사용자 역할 |
| `approval_status` | 승인 상태 |
| `phone_number` | 전화번호 |
| `is_onboarded` | 온보딩 여부 |
| `profile_image` | 프로필 이미지 |
| `last_login` | 마지막 로그인 |
| `is_active` | 활성 사용자 여부 |
| `is_staff` | Staff 여부 |
| `is_superuser` | Superuser 여부 |
| `is_social_account` | 소셜 계정 여부 |
| `date_joined` | 가입일 |
| `primary_email` | 대표 이메일 |
| `participant_id` | Round 참가자 ID |
| `round_id` | Round ID |
| `display_name_snapshot` | 해당 Round 당시 표시 이름 |
| `team_id` | 팀 ID |
| `team_name` | 팀 이름 |

### VIEW SQL

```sql
CREATE OR REPLACE VIEW public.ax_user_team_login_view
AS SELECT DISTINCT ON (u.id) u.id AS user_id,
    u.email AS user_email,
    u.first_name,
    u.last_name,
    u.role,
    u.approval_status,
    u.phone_number,
    u.is_onboarded,
    u.profile_image,
    u.last_login,
    u.is_active,
    u.is_staff,
    u.is_superuser,
    u.is_social_account,
    u.date_joined,
    ea.email AS primary_email,
    rp.id AS participant_id,
    rp.round_id,
    rp.display_name_snapshot,
    t.id AS team_id,
    t.name AS team_name
FROM accounts_user u
LEFT JOIN account_emailaddress ea
    ON ea.user_id = u.id AND ea."primary" = true
LEFT JOIN rounds_roundparticipant rp
    ON rp.user_id = u.id
LEFT JOIN rounds_evaluationround er
    ON er.id = rp.round_id
LEFT JOIN teams_teammembership tm
    ON tm.participant_id = rp.id
LEFT JOIN teams_team t
    ON t.id = tm.team_id
ORDER BY u.id, er.evaluation_start_at DESC NULLS LAST, rp.created_at DESC;
```

### 조회 예시

전체 사용자:

```sql
SELECT *
FROM public.ax_user_team_login_view;
```

특정 사용자:

```sql
SELECT *
FROM public.ax_user_team_login_view
WHERE user_id = 123;
```

---

## 4. Team History VIEW

### VIEW

`public.user_round_team_view`

### 사용 팀

**3조**

### 목적

특정 사용자가 **각 Round에서 어느 팀에 소속되어 있었는지** 확인하기 위한 VIEW입니다.

동일한 사용자가 Round마다 다른 팀에 배정될 수 있으므로 `user_id`와 `round_id`를 기준으로 팀 소속 정보를 확인할 수 있습니다.

### 주요 연결 구조

```text
accounts_user
      │
      ▼
rounds_roundparticipant
      │
      ▼
teams_teammembership
      │
      ▼
teams_team
      ▲
      │
rounds_evaluationround
```

### 제공 컬럼

| 컬럼 | 설명 |
|---|---|
| `user_id` | 사용자 ID |
| `email` | 사용자 이메일 |
| `round_id` | 평가 Round ID |
| `round_title` | Round 제목 |
| `round_status` | Round 상태 |
| `participant_id` | Round 참가자 ID |
| `student_number_snapshot` | 해당 Round 당시 학번 |
| `display_name_snapshot` | 해당 Round 당시 표시 이름 |
| `team_id` | 팀 ID |
| `team_number` | 해당 Round의 팀 번호 |
| `team_name` | 팀 이름 |

### VIEW SQL

```sql
CREATE OR REPLACE VIEW public.user_round_team_view
AS SELECT u.id AS user_id,
    u.email,
    r.id AS round_id,
    r.title AS round_title,
    r.status AS round_status,
    rp.id AS participant_id,
    rp.student_number_snapshot,
    rp.display_name_snapshot,
    t.id AS team_id,
    t.team_number,
    t.name AS team_name
FROM accounts_user u
JOIN rounds_roundparticipant rp
    ON rp.user_id = u.id
JOIN rounds_evaluationround r
    ON r.id = rp.round_id
JOIN teams_teammembership tm
    ON tm.participant_id = rp.id
JOIN teams_team t
    ON t.id = tm.team_id;
```

---

## 5. Team History VIEW 사용 방법

### 5.1 특정 사용자의 Round별 팀 조회

```sql
SELECT
    user_id,
    round_id,
    round_title,
    round_status,
    participant_id,
    student_number_snapshot,
    display_name_snapshot,
    team_id,
    team_number,
    team_name
FROM public.user_round_team_view
WHERE user_id = 123
ORDER BY round_id;
```

예상 결과:

| user_id | round_id | round_title | team_id | team_number | team_name |
|---:|---:|---|---:|---:|---|
| 123 | 1 | 1차 평가 | 10 | 1 | A팀 |
| 123 | 2 | 2차 평가 | 25 | 3 | B팀 |
| 123 | 3 | 3차 평가 | 31 | 2 | C팀 |

---

## 6. 다른 팀 개발 시 권장사항

다른 팀에서는 통합 DB의 원본 테이블을 직접 JOIN하기보다는 가능한 경우 제공된 VIEW를 사용하는 것을 권장합니다.

사용자별 팀 정보가 필요한 경우:

```sql
SELECT *
FROM public.user_round_team_view
WHERE user_id = ?;
```

공통 데이터 연결 로직은 VIEW에서 관리하고 각 팀의 애플리케이션은 VIEW를 조회하는 방식으로 통합합니다.

---

## 7. 주의사항

- VIEW는 조회용 인터페이스입니다.
- 동일 사용자가 여러 Round에서 다른 팀에 소속될 수 있으므로 `user_id + round_id`를 주요 조회 기준으로 사용합니다.
- `student_number_snapshot`, `display_name_snapshot`은 해당 Round 당시의 참가자 정보입니다.
- DB Password는 GitHub에 평문으로 저장하지 않습니다.

---

## 8. 요약

| VIEW | 목적 | 대상 |
|---|---|---|
| `public.ax_user_team_login_view` | 사용자 기본정보 및 대표 팀 정보 | 전체 조 |
| `public.user_round_team_view` | 사용자의 Round별 팀 소속 확인 | 3조 |

`user_round_team_view`는 다음 질문에 답하기 위한 VIEW입니다.

> **이 사용자는 각 Round에서 어느 팀에 소속되어 있었는가?**
