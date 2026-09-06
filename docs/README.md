# 문서 안내

이 디렉터리는 Idea Developer의 현재 정책, 기능, 데이터, API, 테스트와 운영 절차를 설명한다.
구현 과정에서 사용한 과거 시나리오와 프롬프트는 `specs/`에 보관하지만 현재 동작의 근거로
사용하지 않는다.

## 문서 우선순위

문서끼리 내용이 다를 때는 아래 순서를 따른다.

1. `requirements/CURRENT_REQUIREMENTS.md`: 현재 확정된 제품 정책
2. `FUNCTIONAL_SPEC.md`: 사용자 기능, 권한, 상태 변화와 결과
3. `EXCEPTION_CATALOG.md`: 예외 상황과 서버·화면 처리 원칙
4. `api/README.md`: HTTP 계약
5. `database/ERD.md`, `database/DATA_DICTIONARY.md`: 데이터 구조
6. 실제 migration, 서비스 코드와 자동 테스트

문서와 코드가 다르면 추측으로 문서만 고치지 않는다. 요구사항을 먼저 확인한 뒤 코드, 테스트,
문서를 같은 변경 단위에서 맞춘다.

## 목적별 읽기 순서

### 기능을 이해할 때

1. [현재 구현 기준](requirements/CURRENT_REQUIREMENTS.md)
2. [기능 명세](FUNCTIONAL_SPEC.md)
3. [예외 처리 목록](EXCEPTION_CATALOG.md)
4. [API 계약](api/README.md)

### 구조와 DB를 검토할 때

1. [시스템 아키텍처](ARCHITECTURE.md)
2. [ERD](database/ERD.md)
3. [데이터 사전](database/DATA_DICTIONARY.md)
4. [외부 VIEW 연동](integration/VIEW_GUIDE.md)

### 품질과 이관을 확인할 때

1. [최종보고서 도식·양식](report/README.md)
2. [요구사항 추적표](REQUIREMENTS_TRACEABILITY.md)
3. [테스트·보안·운영 품질](QUALITY_ASSURANCE.md)
4. [제품 결정 기록](decisions/README.md)
5. [부모 프로젝트 이관](08_PARENT_HANDOFF.md)
6. [소스 전달 양식](integration/SOURCE_DELIVERY_TEMPLATE.md)

### 개발 환경과 협업을 시작할 때

`00_START_HERE.md`부터 번호 순서대로 읽는다. 팀원이 기능을 전달할 때는
`integration/SOURCE_DELIVERY_TEMPLATE.md`를 사용한다.

## 문서 갱신 규칙

- 기능 또는 권한 변경: 현재 구현 기준, 기능 명세, 예외 목록과 관련 테스트를 함께 갱신한다.
- API 변경: API 계약과 프론트 호출부, 회귀 테스트를 함께 갱신한다.
- 모델 또는 migration 변경: ERD와 데이터 사전을 함께 갱신한다.
- 운영 작업 변경: 품질 문서와 환경변수 예시를 함께 갱신한다.
- 확정되지 않은 항목은 구현된 것처럼 쓰지 않고 `보류` 또는 `부모팀 협의`로 표시한다.
