# 기여 가이드

Idea Developer에 변경을 제안할 때는 기능, 테스트, 문서가 서로 일치하도록 관리합니다.

## 개발 절차

1. 변경 목적과 영향 범위를 확인합니다.
2. 현재 기준 브랜치에서 짧은 작업 브랜치를 만듭니다.
3. 관련 코드와 테스트를 함께 수정합니다.
4. migration이 필요한 모델 변경은 새 migration으로 추가합니다.
5. 전체 테스트와 Ruff 검사를 실행합니다.
6. 변경 이유와 검증 결과를 Pull Request에 기록합니다.

```powershell
git switch -c feat/short-description
python manage.py test --settings=config.settings.test
python -m ruff check .
git status
git diff --check
```

## 변경 원칙

- 인증과 권한은 모든 관련 API에서 서버가 검사해야 합니다.
- 외부 PostgreSQL VIEW는 조회 전용으로 유지합니다.
- 기존 migration을 수정하지 않고 새 migration을 추가합니다.
- API 계약을 바꾸면 호출하는 화면과 API 문서를 함께 갱신합니다.
- 버그 수정에는 실패 상황을 재현하는 회귀 테스트를 추가합니다.
- 관련 없는 코드 정리나 대규모 포맷 변경을 한 변경에 섞지 않습니다.

## 보안

다음 항목은 저장소에 커밋하지 않습니다.

- `.env`
- 실제 비밀번호와 API 키
- 운영 데이터베이스 dump
- 사용자 개인정보
- 개인용 로그와 로컬 산출물

예제 값은 실제 환경에서 사용할 수 없는 placeholder만 사용합니다.

## Pull Request 설명

변경한 기능과 이유, 주요 구현 방식, 실행한 테스트, migration·환경변수 변경 여부, 알려진 제한을 기록합니다. 화면 변경이 있다면 전후 이미지를 첨부합니다.

검토가 끝나기 전에는 공유 브랜치의 이력을 강제로 변경하지 않습니다.
