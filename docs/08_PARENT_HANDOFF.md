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

- 독립 이메일 OTP 로그인 → 부모 `request.user` 세션 (독립 저장소에서는 OTP를 유지하고,
  제거·교체는 병합된 통합 저장소에서 수행)
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

독립 시스템의 삭제 정책은 PRD를 30일간 복구 가능 상태로 보관한 뒤 상세 변경·AI·기여도
기록과 함께 영구 삭제하는 것입니다. PRD FK가 없는 `PrdDeletionAuditLog`에는 삭제된 PRD ID,
제목 스냅샷, 생성자·실행자와 삭제 시각만 남깁니다. 이 로그는 규제 준수용 전체 감사 원장이
아니라 삭제 사실을 확인하기 위한 최소 기록입니다. 부모가 별도의 공통 감사 원장을 요구하면
보존기간과 책임 주체는 통합 단계에서 추가로 정합니다.

## 추가 인프라 선택사항

현재 부모 저장소에는 Redis, Celery, Django Channels가 없습니다. 독립 MVP는 PostgreSQL 작업 worker와 HTTP polling을 사용합니다. 부모 팀이 진짜 실시간 커서·프레즌스를 원하면 Redis와 Channels 도입 범위를 별도로 검토해야 합니다.

## Slack 알림 이관

부모 프로젝트에 포함되는 `notifications.slack`의 공통 함수만 사용합니다. 이 저장소는
Slack Member ID를 저장하지 않으며 부모 `accounts_user.id`와 같은 외부 `user_id`를 전달합니다.

- 신규 PRD 또는 기존 PRD에 참여자가 추가되면 해당 참여자에게 알림
- PRD 코멘트가 생성되면 작성자를 제외한 대상 참여자에게 알림
- 부모 모듈이 없는 독립 개발 환경에서는 도메인 저장을 실패시키지 않고 알림만 건너뜀

현재 호출은 DB commit 이후 실행하며 별도 비동기 큐를 도입하지 않습니다. 호출 중 예외가
발생하면 짧은 지수형 대기로 최대 3회 재시도하고, 최종 Slack 발송 실패도 PRD 참여자 추가나
코멘트 저장을 취소하지 않습니다. 재시도 횟수와 최초 대기 시간은 각각
`SLACK_DELIVERY_MAX_ATTEMPTS`, `SLACK_DELIVERY_RETRY_BASE_SECONDS`로 조정합니다.

## 소스 전달

4조 통합팀에 전달할 때는 코드만 보내지 않고
`docs/integration/SOURCE_DELIVERY_TEMPLATE.md`에 기준 commit, 변경 범위, migration,
requirements, 환경변수와 테스트 결과를 함께 기록합니다.
