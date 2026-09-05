# 현재 구현 기준

이 문서는 초기 단계별 프롬프트 이후 변경된 결정을 포함한 현재 구현 기준입니다. 초기 프롬프트와
충돌하면 이 문서와 제품 기준 문서의 최신 내용을 우선하며, 보류 항목은 임의로 확장하지 않습니다.

## 확정

| 영역 | 현재 기준 |
|---|---|
| 기술 스택 | Django, Bootstrap 5.3.2, PostgreSQL |
| 브레인스토밍 UI | React·ReactDOM 고정 버전 CDN, JSX/Babel 런타임 없음 |
| 협업 | HTTP polling, cursor 증분 조회, resource version 충돌 검사 |
| 비동기 작업 | PostgreSQL 작업 테이블과 Django management command worker |
| 사용자 원장 | 부모 VIEW가 진실의 원천이며 자식은 최소 세션 매핑만 저장 |
| 독립 인증 | 단독 실행에서는 이메일 OTP 로그인을 유지하고, 부모 인증 교체는 통합 저장소에서 처리 |
| PRD 역할 | owner, editor, tutor, viewer; 모든 권한은 서버에서 재검사 |
| 회차 | 회차 없는 개인·일반 팀 PRD를 허용하고 명시적 참여자로 접근 제어 |
| 회차 팀 PRD | `user_id + round_id` VIEW 참가정보와 현재 팀을 검증 |
| 과거 PRD | 현재 회차와 관계없이 명시적 참여자는 조회 가능 |
| 참여자 | 초대 수락 없이 즉시 추가하며 추가·역할 변경·제거 지원 |
| 질문 보류 | 완성도와 AI PRD 충족도 입력에서 제외 |
| 브레인스토밍 분류 결과 | AI 호출 없이 서버의 현재 섹션·상태 통계를 표시 |
| 메모 상태 | 미분류는 default, 섹션 배치 시 accepted, 보류 구역은 held |
| 보드 버전 | PRD마다 여러 버전, 최초 진입은 최신 버전, 과거 버전 조회·편집 가능 |
| 기여도 | 의미 있는 동일 lineage 메모의 작성자와 내용 편집자에게 각각 기여 인정 |
| 기여도 공개 | staff/superuser 관리자만 결과 조회 가능 |
| 삭제 | PRD와 메모는 30일 소프트 삭제 후 자정 유지보수에서 영구 삭제 |
| 삭제 기록 | 영구 삭제 시 상세 변경·AI·기여도 기록도 삭제하고 독립 삭제 사실 로그만 장기 보존 |
| 알림 | PRD 참여자 추가와 코멘트 생성 시 부모 Slack 공통 함수를 DB commit 이후 호출하며, 별도 비동기 큐 없이 일시적 실패를 최대 3회 재시도하고 최종 실패가 본 기능 저장을 취소하지 않게 처리 |

## 제거됨

- 브레인스토밍 Markdown 내보내기

브레인스토밍 Markdown 내보내기는 화면뿐 아니라 API와 백엔드 구현도 제거하며 다시 구현하지
않습니다. PRD 작성 화면의 Markdown 내보내기는 별도 기능으로 유지합니다.

## 현재 사용자 화면에서 제공하지 않음

- AI 브레인스토밍 분석
- AI 항목 분류 및 추천 적용
- AI 사용 기록 화면
- PRD 수정 이력 화면
- 사용자가 직접 실행하는 즉시 영구 삭제

기존 migration과 과거 로그를 보존해야 하므로 관련 DB enum이나 기록을 제거할 때는 별도 데이터
이관 계획을 세웁니다. 현재 URL에 남은 AI Legacy API의 제거 여부도 기존 호출자를 확인한 뒤
결정합니다.

## 보류 또는 부모팀 협의 필요

- 기여도 점수의 부모 전달 API·payload·멱등성 규격
- 부모 `results_scoreinput` 도입 여부
- 부모 이관 이후 부모가 추가로 요구하는 공통 감사 로그의 소유자와 보존기간

## 기준 문서

- `docs/specs/home-backend-scenario.md`
- `docs/specs/brainstorm-backend-scenario.md`
- `docs/integration/VIEW_GUIDE.md`
- 이 문서에 기록된 이후 확정 변경사항
