# 03. 브랜치·커밋·Pull Request

## 브랜치 이름

형식은 `<종류>/<짧은-영문-설명>`입니다.

| 종류 | 사용 시점 | 예시 |
|---|---|---|
| `feat` | 새 기능 | `feat/login-otp-ui` |
| `fix` | 버그 수정 | `fix/prd-deadline` |
| `test` | 테스트 추가 | `test/node-conflict` |
| `docs` | 문서 | `docs/local-setup` |
| `refactor` | 동작 유지 구조 개선 | `refactor/context-resolver` |
| `chore` | 설정·도구 | `chore/ruff-config` |

한글, 공백, 개인 이름만 있는 브랜치명은 피합니다. 파일 전달 작업은 `setup/config-settings`, `feat/login-template`처럼 파일의 역할을 이름에 넣습니다.

## commit 메시지

형식:

```text
종류: 무엇을 변경했는지
```

좋은 예:

```text
feat: 이메일 인증번호 입력 화면 추가
fix: 만료된 인증번호가 재사용되는 문제 수정
test: 비활성 사용자의 로그인 거절 테스트 추가
docs: Windows 가상환경 실행법 추가
```

나쁜 예:

```text
수정
완성
test
최종진짜최종
```

## commit 크기

- 한 commit에는 한 가지 이유의 변경만 넣습니다.
- 코드와 그 코드의 테스트는 같은 commit에 넣어도 됩니다.
- 자동 생성 파일 수백 개를 기능 코드와 섞지 않습니다.
- commit 전 `git diff --staged`로 실제 포함 내용을 봅니다.

## PR 작성

제목 예:

```text
[FEAT] 이메일 OTP 로그인 화면과 검증 API 추가
```

본문에는 다음을 작성합니다.

```text
## 변경 내용
- 이메일 입력 화면 추가
- 인증번호 검증 API 연결

## 확인 방법
1. 개발 서버 실행
2. /login/ 접속
3. 콘솔 이메일의 코드 입력

## 테스트
- python manage.py test accounts

## 참고
- 실제 SMTP는 아직 연결하지 않음
```

## 리뷰하는 법

- 먼저 직접 실행 가능한지 확인합니다.
- 요구사항과 다른 동작을 구체적으로 적습니다.
- 사람을 평가하지 않고 코드를 설명합니다.
- 수정이 꼭 필요하면 `변경 요청`, 제안이면 `선택 제안`이라고 구분합니다.

## 파일별 전달 작업의 PR 대상

- 팀원 PR: 개인 branch → `develop`
- 단계 완료 PR: `develop` → `main`
- 파일 하나만 추가해 아직 앱이 실행되지 않는다면 PR에 `단계 조립 전이라 단독 실행 불가`라고 적습니다.
- 의존 파일이 모두 합쳐진 뒤 팀장이 전체 check와 test를 실행합니다.
