# 부모 시스템 통합 체크리스트

## 1. 통합 전

- [ ] 전달 branch와 commit SHA를 고정하고 `SOURCE_DELIVERY_CURRENT.md`와 일치하는지 확인
- [ ] 부모 저장소의 Python·Django·Bootstrap·PostgreSQL 버전과 requirements 충돌 확인
- [ ] 부모 DB와 분리된 staging DB 백업 및 migration 복구 절차 준비
- [ ] 부모의 `accounts`, `notifications`, 공통 template과 URL 연결 지점 확인
- [ ] 실제 비밀값 없이 필요한 환경변수 이름만 배포 설정에 등록

## 2. 코드 통합

- [ ] `apps/prds`, `apps/brainstorm`, `apps/ai`, `apps/jobs` 비즈니스 모델과 서비스 우선 통합
- [ ] `apps/integration`의 VIEW repository와 Context resolver를 부모 인증 방식에 맞게 연결
- [ ] 독립 `LocalUserMapping`은 회원 원장으로 사용하지 않고 부모 `accounts_user.id` 매핑만 유지
- [ ] 독립 OTP URL은 부모 인증 연결이 끝난 뒤 통합 URL에서 제거하거나 비노출 처리
- [ ] `idea-developer`의 `/ideas/` 화면 URL과 `/api/v1/` API include를 부모 URL에 연결
- [ ] 부모 base template에 `extra_head`, `breadcrumb`, `content`, `modals`, `extra_js` block 제공
- [ ] Bootstrap 5.3.2와 브레인스토밍 React·ReactDOM CDN origin을 부모 CSP에 허용
- [ ] CSRF cookie·trusted origin·로그인 redirect가 부모 설정에서 유지되는지 확인

## 3. 데이터베이스

- [ ] 자식 app migration graph를 부모 migration graph와 함께 검사
- [ ] `public.ax_user_team_login_view`, `public.user_round_team_view` 조회 권한 부여
- [ ] VIEW 모델이 `managed=False`이고 VIEW DDL migration이 없는지 확인
- [ ] `POSTGRES_OPTIONS`의 `search_path`가 자식 schema와 `public`을 모두 찾는지 확인
- [ ] 최종 PRD 템플릿 30/32/32문항 생성 결과 확인
- [ ] 실제 운영 데이터가 있다면 질문 갱신 migration 적용 전 staging 비교
- [ ] version·idempotency·soft delete·유니크 제약이 PostgreSQL에서 동작하는지 확인

## 4. 외부 기능

- [ ] `notifications.slack` import와 단건·batch 함수 signature 확인
- [ ] `DJANGO_SITE_URL`을 실제 HTTPS 서비스 origin으로 설정하고 초대 PRD 링크 클릭 확인
- [ ] Slack 미연동 사용자와 전송 실패가 PRD 저장을 취소하지 않는지 확인
- [ ] `GEMINI_API_KEY`를 배포 비밀 저장소에 등록하고 저장소·로그에 노출되지 않는지 확인
- [ ] 웹과 별도로 `run_job_worker` 프로세스를 실행하고 재시작 정책 구성
- [ ] 자정에 `run_midnight_maintenance`가 한 번 실행되도록 scheduler 구성

## 5. 권한·화면 회귀 검증

- [ ] owner/editor/tutor/viewer별 PRD·코멘트·브레인스토밍 권한 확인
- [ ] 회차 없음, 현재 회차, 과거 회차 PRD 조회·쓰기 범위 확인
- [ ] 완료 후 편집 잠금, owner/관리자 재개, tutor 리뷰 예외 확인
- [ ] 홈의 내 PRD·참여 PRD·튜터 관리 탭과 복합 필터 확인
- [ ] PRD 생성·편집·삭제·휴지통 복구와 redirect 확인
- [ ] 브레인스토밍 최신 보드 편집, 이전 보드 읽기, 최신 지정·삭제 후 권한 이동 확인
- [ ] 메모 drag·다중 선택·undo/redo·연결선·보류·복원과 `409` 충돌 확인
- [ ] AI 코치·질문 초안·관점별 종합 진단·PRD 반영의 worker 완료 흐름 확인

## 6. 최종 검증과 전달

- [ ] `manage.py check`, migration dry-run, 전체 Django 테스트와 Ruff 실행
- [ ] PostgreSQL 전용 동시성 테스트를 분리된 테스트 DB에서 실행
- [ ] DEBUG 전용 로그인 URL이 운영 설정에서 404인지 확인
- [ ] `.env`, API 키, DB dump, 개인정보와 로컬 산출물이 Git에 없는지 확인
- [ ] Base Branch, Base Commit, Work Branch, Latest Commit과 변경 파일 목록 전달
- [ ] migration·requirements·환경변수·테스트 결과·보류사항을 전달 메시지에 첨부

통합 완료 판단은 화면이 열리는 것만으로 하지 않습니다. 부모 인증 사용자로 VIEW 조회,
PRD 생성, 참여자 Slack 링크, 협업 충돌, AI worker, 자정 유지보수까지 staging에서 확인해야
완료입니다.
