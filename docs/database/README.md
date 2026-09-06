# 데이터베이스 설계 문서

이 폴더는 Django 모델과 migration을 기준으로 작성한 현재 데이터베이스 구조를 설명한다.

- `ERD.md`: 도메인별 테이블 관계와 부모 VIEW 연동 경계
- `DATA_DICTIONARY.md`: 테이블 목적, 핵심 키, 무결성·보존 정책

실제 schema의 최종 근거는 Django migration이다. 모델이나 제약조건을 변경하면 migration, ERD,
데이터 사전과 관련 테스트를 같은 Pull Request에서 갱신한다.

## 설계 원칙

- 제품 데이터는 PostgreSQL의 `idea_developer` schema에 저장한다.
- 부모 사용자·회차·팀 원장은 복제하지 않고 `public` schema의 두 VIEW를 읽기 전용으로 조회한다.
- 부모 VIEW의 외부 ID에는 자식 DB FK를 만들지 않고 서비스 계층에서 유효성을 검증한다.
- 자식이 소유하는 관계에는 FK, unique/check constraint와 애플리케이션 검증을 함께 적용한다.
- 동시 편집 resource는 version을 사용하고, 중복 생성 위험이 있는 요청은 idempotency key를 쓴다.
- PRD와 메모는 30일 소프트 삭제 후 자정 유지보수에서 영구 삭제한다.
