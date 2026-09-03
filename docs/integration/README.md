# 외부 연동 문서

부모 시스템이 제공한 VIEW 규격과 이관 계약을 보관합니다.

실제 DB 비밀번호, API 키, 사용자 데이터 export는 이 폴더에 commit하지 않습니다.

## 구현 계약

- 조회 대상은 `public.ax_user_team_login_view`, `public.user_round_team_view` 두 개뿐입니다.
- 원본 `accounts_user`, `rounds_*`, `teams_*` 테이블을 직접 조회하거나 JOIN하지 않습니다.
- Django 모델은 `managed=False`이고 VIEW DDL migration은 만들지 않습니다.
- 현재 회차 팀은 반드시 `user_id + round_id`로 `user_round_team_view`에서 확인합니다.
- `ax_user_team_login_view`의 대표 `team_id`는 현재 회차 팀 판정에 사용하지 않습니다.
- 진행 중 회차의 실제 status 문자열은 부모 팀 확인 후 `INTEGRATION_ACTIVE_ROUND_STATUSES`로 설정합니다.
- VIEW 오류, 설정 누락, 복수 팀 데이터는 쓰기 권한을 추측하지 않고 fail closed합니다.

구현 파일은 `apps/integration/models.py`, `repository.py`, `context.py`이며 테스트 fixture는 `tests/fixtures/integration_views.py`에 있습니다.
