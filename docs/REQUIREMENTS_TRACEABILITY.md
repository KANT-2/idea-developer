# 요구사항 추적표

핵심 Business Rule이 구현 코드와 자동 테스트에 연결되어 있는지 확인하기 위한 색인이다. 파일
경로는 책임의 중심을 나타내며 세부 호출 관계는 코드와 테스트를 최종 근거로 사용한다.

| 요구사항 | 주요 구현 | 대표 테스트 |
|---|---|---|
| 부모 VIEW 읽기 전용·직접 JOIN 금지 | `apps/integration/models.py`, `repository.py`, DB router | `test_integration_models.py`, `test_integration_repository.py` |
| session 사용자와 외부 user ID 매핑 | `apps/accounts/models.py`, `apps/integration/context.py` | `test_authentication.py`, `test_integration_context.py` |
| OTP 보안과 DEBUG 로그인 격리 | `apps/accounts/services.py`, `views.py`, production checks | `test_authentication.py`, `test_debug_login.py`, `test_production_settings.py` |
| 회차 없는·과거 PRD 접근 | `apps/prds/services.py`, `home.py`, IntegrationContext | `test_prd_api.py`, `test_home_api.py` |
| PRD 템플릿·상태·완성도 단일 계산 | `apps/prds/models.py`, template data migrations | `test_prd_models.py`, `test_demo_seed.py` |
| PRD 생성 idempotency·참여자 중복 방지 | `apps/prds/services.py`, DB unique constraints | `test_prd_api.py`, `test_prd_models.py` |
| 홈 KPI·필터·정렬·페이지네이션 | `apps/prds/home.py`, `home_views.py` | `test_home_api.py` |
| 질문 보류 완성도·AI 입력 제외 | `apps/prds/models.py`, `detail_views.py`, `apps/ai/evaluation.py` | `test_prd_models.py`, `test_prd_detail_api.py`, `test_ai_prd_evaluation.py` |
| PRD·참여자·코멘트 동시 수정 보호 | `apps/prds/detail_views.py`, `comment_services.py` | `test_edit_concurrency.py`, `test_prd_detail_api.py` |
| PRD 완료 잠금과 owner·관리자 재개 | `apps/prds/status_services.py`, permissions | `test_prd_detail_api.py`, `test_permissions.py` |
| PRD 휴지통·30일 보존 | `apps/prds/detail_views.py`, `apps/jobs/cleanup.py` | `test_prd_detail_api.py`, `test_midnight_maintenance.py` |
| 캔버스 버전과 lineage 보존 | `apps/brainstorm/models.py`, `services.py` | `test_brainstorm_models.py`, `test_brainstorm_api.py` |
| 메모 이동·보류·연결선 무결성 | `apps/brainstorm/services.py` | `test_brainstorm_api.py`, `test_brainstorm_models.py` |
| polling cursor와 전체 재동기화 | `apps/brainstorm/views.py`, 브레인스토밍 JS | `test_brainstorm_api.py`, `test_templates.py` |
| AI 작업 lock·lease·취소·재시도 | `apps/ai/services.py`, `worker.py` | `test_ai_infrastructure.py`, `test_worker.py` |
| Gemini schema·ID·prompt injection 방어 | `apps/ai/gemini.py`, `providers.py`, 기능별 processor | `test_gemini_provider.py`, `test_brainstorm_ai.py` |
| AI 코치 대화 append·30일 TTL | `apps/ai/coaching.py`, `apps/jobs/cleanup.py` | `test_ai_coaching.py`, `test_brainstorm_export_cleanup.py` |
| 관점별 PRD 전체 초안·선택 승인·version 검증 | `apps/ai/perspective_draft.py`, `apps/ai/views.py`, PRD 작성 JS | `test_ai_perspective_draft.py` |
| AI PRD 미리보기·승인·version·멱등성 | `apps/ai/prd_apply.py`, brainstorm AI views | `test_prd_apply_ai.py` |
| 기여도 lineage·반영 confidence·50:50 | `apps/ai/contribution.py` | `test_contribution_evaluation.py` |
| Slack 참여자·코멘트 알림과 실패 격리 | `apps/common/slack_notifications.py`, PRD services | `test_slack_notifications.py` |
| 자정 자동 완료·영구 삭제 | `run_midnight_maintenance`, cleanup service | `test_midnight_maintenance.py` |
| 구조화 로그의 request ID·extra·예외 보존 | `apps/common/logging.py`, `apps/ai/worker.py` | `test_logging.py`, `test_ai_infrastructure.py` |

요구사항을 변경할 때는 이 표의 구현 파일과 대표 회귀 테스트를 함께 검토한다. 새로운 핵심 규칙에
테스트 근거가 없다면 완료로 표시하지 않는다.
