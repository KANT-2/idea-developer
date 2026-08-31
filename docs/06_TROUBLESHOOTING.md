# 06. 자주 생기는 문제

## 현재 branch를 모르겠어요

```bash
git branch --show-current
git status
```

`main`이면 코드를 수정하기 전에 새 branch를 만듭니다.

## pull했더니 충돌이 났어요

1. 당황해서 파일을 지우지 않습니다.
2. `git status`로 충돌 파일을 확인합니다.
3. 파일의 `<<<<<<<`, `=======`, `>>>>>>>` 사이에서 필요한 내용을 합칩니다.
4. 표시 줄을 모두 삭제합니다.
5. 실행·테스트 후 파일을 add하고 commit합니다.

```bash
git add <해결한-파일>
git commit -m "merge: main 변경과 로그인 화면 충돌 해결"
```

모르겠으면 `git status` 결과와 충돌 파일을 팀원에게 보여줍니다. 무작정 `--force`를 사용하지 않습니다.

## 잘못된 파일을 add했어요

commit 전:

```bash
git restore --staged <파일>
```

파일 내용은 남고 staging에서만 빠집니다.

## 마지막 commit 메시지만 바꾸고 싶어요

아직 push하지 않았다면:

```bash
git commit --amend -m "올바른 메시지"
```

이미 공유 branch에 push했다면 혼자 amend·force push하지 말고 팀원에게 먼저 알립니다.

## `.env`를 실수로 commit했어요

즉시 팀장에게 알리고 노출된 비밀번호·키를 폐기하고 재발급합니다. 파일만 삭제해도 Git 기록에는 비밀이 남을 수 있습니다.

```bash
git rm --cached .env
git commit -m "fix: 저장소에서 환경변수 파일 제거"
```

그 후 키 회전과 기록 제거는 팀장이 처리합니다.

## migration 충돌

두 branch가 같은 app의 migration을 만들면 번호가 겹칠 수 있습니다. 두 PR을 동시에 merge하지 말고 첫 PR merge 후 두 번째 담당자가 main을 가져와 다시 `makemigrations`하고 테스트합니다.

## 서버가 안 켜져요

```bash
python manage.py check
python manage.py showmigrations
```

가상환경 활성화, 의존성 설치, `.env`, PostgreSQL 실행 여부를 차례로 확인합니다.
