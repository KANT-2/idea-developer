# 제품 결정 기록

이 폴더는 변경 이유가 중요한 제품·아키텍처 결정을 보존한다. 현재 결정의 요약은
`../requirements/CURRENT_REQUIREMENTS.md`가 최우선 기준이며, 아래 목록은 결정 배경을 찾기 위한
색인이다.

## 확정 결정

| 결정 | 현재 결론 |
|---|---|
| 실행 형태 | 부모 저장소를 수정하지 않는 독립 Django 시스템으로 완성 |
| UI | 일반 화면은 Django template·Bootstrap, 브레인스토밍만 React CDN |
| 협업 | HTTP polling과 resource version 충돌 검사 |
| AI 작업 | PostgreSQL 작업 테이블과 management command worker |
| 인증 | 독립 저장소에서는 OTP 유지, 부모 이관 시 부모 session resolver로 교체 |
| 회차 | 회차 없는 PRD와 과거 회차 PRD 허용, 회차 팀 쓰기만 VIEW 참가정보 재검증 |
| 참여자 | 초대 수락 없이 즉시 추가, 역할 변경·제거 지원 |
| 메모 상태 | 미분류 default, 섹션 배치 accepted, 보류 영역 held |
| 보드 버전 | `display_order` 첫 보드가 최신이며 최신만 편집 가능, 이전 버전은 조회 전용, 최신 삭제 시 다음 보드 승격 |
| 기여도 | 실제 PRD 반영 lineage의 작성자·내용 편집자와 reflection confidence 사용 |
| 기여도 공개 | staff/superuser 관리자만 조회 |
| 삭제 | 30일 소프트 삭제 후 자정 유지보수에서 영구 삭제 |
| Slack | DB commit 후 부모 공통 함수 호출, 최대 3회 재시도, 도메인 저장은 유지 |
| 제거 기능 | 브레인스토밍 Markdown 내보내기, 사용자용 AI 분석·항목 분류 |

## 미결정·통합 협의

- 기여도 점수의 부모 전달 payload, 인증과 idempotency 규격
- 부모 `results_scoreinput` 도입 여부
- 부모 이관 이후 추가 공통 감사 로그의 책임 주체와 보존기간

새 결정을 추가할 때는 결정일, 배경, 선택지, 결론, 영향받는 코드·migration·문서를 별도 Markdown
파일로 기록한다. 기존 결정을 조용히 덮어쓰지 않고 변경 이유와 데이터 이관 영향을 남긴다.
