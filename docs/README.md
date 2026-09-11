# 기술 문서

이 디렉터리는 Idea Developer의 제품 동작, 설계, API, 데이터 구조, 운영 방법을 설명합니다.

## 처음 읽는 순서

1. [프로젝트 개요와 실행 방법](../README.md)
2. [로컬 개발 환경](01_LOCAL_SETUP.md)
3. [프로젝트 구조](04_PROJECT_STRUCTURE.md)
4. [기능 명세](FUNCTIONAL_SPEC.md)
5. [시스템 아키텍처](ARCHITECTURE.md)

## 문서 분류

### 제품과 기능

- [현재 요구사항](requirements/CURRENT_REQUIREMENTS.md)
- [기능 명세](FUNCTIONAL_SPEC.md)
- [예외 처리 목록](EXCEPTION_CATALOG.md)
- [화면 흐름](report/SCREEN_FLOW.md)
- [사용 사례](report/USE_CASES.md)

### 개발과 구조

- [로컬 개발 환경](01_LOCAL_SETUP.md)
- [프로젝트 구조](04_PROJECT_STRUCTURE.md)
- [문제 해결](06_TROUBLESHOOTING.md)
- [기여 방법](../CONTRIBUTING.md)

### API와 데이터

- [API 문서](api/README.md)
- [데이터베이스 안내](database/README.md)
- [ERD](database/ERD.md)
- [데이터 사전](database/DATA_DICTIONARY.md)
- [외부 PostgreSQL VIEW 연동](integration/VIEW_GUIDE.md)

### 아키텍처와 품질

- [시스템 아키텍처](ARCHITECTURE.md)
- [데이터 흐름](report/DATA_FLOW.md)
- [배포 구조](report/DEPLOYMENT_DIAGRAM.md)
- [시퀀스 다이어그램](report/SEQUENCE_DIAGRAMS.md)
- [상태 다이어그램](report/STATE_DIAGRAMS.md)
- [품질 보증](QUALITY_ASSURANCE.md)
- [요구사항 추적표](REQUIREMENTS_TRACEABILITY.md)

## 문서 관리 원칙

- 현재 동작과 일치하는 내용만 사용자·개발자 문서에 기록합니다.
- 기능 변경 시 관련 API, 데이터 구조, 테스트 설명도 함께 갱신합니다.
- 확정되지 않은 계획은 현재 기능처럼 표현하지 않습니다.
- 개인 이름, 임시 담당자, 작업용 브랜치, 대화형 프롬프트 등 개발 과정의 기록은 제품 문서에 포함하지 않습니다.
- 실제 비밀번호, API 키, 사용자 개인정보를 문서나 예제에 기록하지 않습니다.

`specs/`, `updates/`, 일부 integration 문서는 구현 배경이나 이전 전달 기록을 보관합니다. 현재 동작을 확인할 때는 코드, migration, 자동 테스트와 위의 핵심 문서를 우선하세요.
