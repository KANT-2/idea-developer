# 최종보고서 도식·양식 모음

이 디렉터리는 Idea Developer의 설계와 구현 결과를 일관된 형식으로 설명하기 위한 도식과 보고서
양식을 모은다. 각 도식은 실제 Django URL, 서비스 경계, 모델과 현재 정책을 기준으로 작성한다.

## 문서 구성

| 문서 | 용도 |
|---|---|
| [최종보고서 양식](FINAL_REPORT_TEMPLATE.md) | 프로젝트 배경부터 결과·한계까지 작성하는 기본 목차 |
| [기능 구성도·유스케이스](USE_CASES.md) | 사용자 역할별 기능과 권한 범위 설명 |
| [화면 흐름도](SCREEN_FLOW.md) | 로그인부터 홈, PRD, 브레인스토밍, 휴지통까지 화면 이동 설명 |
| [주요 시퀀스](SEQUENCE_DIAGRAMS.md) | 생성·저장·협업·AI·삭제의 서버 처리 순서 설명 |
| [데이터 흐름도](DATA_FLOW.md) | 부모 VIEW, Django, PostgreSQL, Gemini, Slack 사이 데이터 이동 설명 |
| [상태 전이도](STATE_DIAGRAMS.md) | PRD·질문·메모·AI job·삭제 상태 변화 설명 |
| [배포 구성도](DEPLOYMENT_DIAGRAM.md) | web·worker·자정 유지보수와 외부 서비스 배치 설명 |
| [테스트 결과 양식](TEST_REPORT_TEMPLATE.md) | 테스트 환경, 명령, 결과와 결함 근거 기록 |

데이터 구조는 [ERD](../database/ERD.md)와 [데이터 사전](../database/DATA_DICTIONARY.md), 실행 구조는
[시스템 아키텍처](../ARCHITECTURE.md)를 사용한다. 기능과 예외 설명은
[기능 명세](../FUNCTIONAL_SPEC.md), [예외 처리 목록](../EXCEPTION_CATALOG.md)을 기준으로 한다.

## 도식 관리 원칙

- 화면이나 API가 바뀌면 해당 흐름도와 시퀀스를 같은 변경에서 수정한다.
- 구현되지 않은 기능은 실선 흐름으로 표현하지 않는다.
- 부모 시스템과 자식 시스템의 책임 경계를 항상 구분한다.
- 외부 ID와 자식 DB FK를 같은 관계처럼 표현하지 않는다.
- Mermaid 원본을 유지하여 GitHub에서 확인하고 변경 이력을 추적한다.
