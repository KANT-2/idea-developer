# 08. 부모 프로젝트 이관 메모

우리 팀의 납품물은 독립 Django 시스템입니다. 부모 저장소에 실제로 합치는 작업은 부모 운영 팀이 담당합니다.

## 맞춘 호환 기준

- Django 5.2.x
- Bootstrap 5.3.2
- PostgreSQL
- URL namespace `ideas` 권장
- 기본 URL `/ideas/` 권장
- template block: `extra_head`, `breadcrumb`, `content`, `modals`, `extra_js`
- React CDN은 브레인스토밍 화면에만 사용
- 사용자·회차·팀은 제공 VIEW로 읽기

## 부모 팀이 교체할 지점

- 독립 이메일 OTP 로그인 → 부모 `request.user` 세션
- standalone `IntegrationContextResolver` → 부모 인증 resolver
- 독립 `base.html` → 부모 `templates/base.html`
- 독립 URL include → 부모 `config/urls.py`
- 독립 사용자 매핑 모델 → 부모 User 연결 정책

## 그대로 유지할 지점

- PRD·브레인스토밍 비즈니스 규칙
- 외부 `user_id`, `round_id`, `participant_id`, `team_id` 계약
- PRD별 owner/editor/tutor/viewer 권한
- version 충돌과 idempotency 규칙
- 소프트 삭제, 감사 로그, AI 사용 로그

## 추가 인프라 선택사항

현재 부모 저장소에는 Redis, Celery, Django Channels가 없습니다. 독립 MVP는 PostgreSQL 작업 worker와 HTTP polling을 사용합니다. 부모 팀이 진짜 실시간 커서·프레즌스를 원하면 Redis와 Channels 도입 범위를 별도로 검토해야 합니다.
