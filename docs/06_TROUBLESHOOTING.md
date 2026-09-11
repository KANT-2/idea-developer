# 06. 자주 생기는 문제

## 현재 branch를 모르겠어요

```bash
git branch --show-current
git status
```

통합 대상 브랜치라면 코드를 수정하지 말고 새 작업 브랜치로 전환합니다.

## pull했더니 충돌이 났어요

1. 당황해서 파일을 지우지 않습니다.
2. `git status`로 충돌 파일을 확인합니다.
3. 파일의 `<<<<<<<`, `=======`, `>>>>>>>` 사이에서 필요한 내용을 합칩니다.
4. 표시 줄을 모두 삭제합니다.
5. 실행·테스트 후 파일을 add하고 commit합니다.

```bash
git add <해결한-파일>
git commit -m "merge: develop 변경과 로그인 화면 충돌 해결"
```

원인을 확인할 수 없다면 `git status` 결과와 충돌 파일을 저장소 관리자에게 전달합니다. 무작정 `--force`를 사용하지 않습니다.

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

이미 공유 branch에 push했다면 amend·force push 전에 저장소 관리자와 영향을 확인합니다.

## `.env`를 실수로 commit했어요

즉시 저장소 관리자에게 알리고 노출된 비밀번호·키를 폐기하고 재발급합니다. 파일만 삭제해도 Git 기록에는 비밀이 남을 수 있습니다.

```bash
git rm --cached .env
git commit -m "fix: 저장소에서 환경변수 파일 제거"
```

그 후 키 회전과 Git 기록 제거 절차를 진행합니다.

## migration 충돌

두 branch가 같은 app의 migration을 만들면 번호가 겹치거나 migration graph에 leaf가 여러 개 생길
수 있습니다. 파일 번호를 임의로 바꾸거나 기존 migration을 삭제하지 않습니다. 첫 PR을
`develop`에 병합한 뒤 두 번째 브랜치에 최신 `develop`을 합치고, Django가 두 leaf를 모두
의존하는 merge migration을 만들 수 있는지 확인합니다.

```bash
python manage.py makemigrations <app-name> --merge
python manage.py migrate
python manage.py test --settings=config.settings.test
```

## 서버가 안 켜져요

```bash
python manage.py check
python manage.py showmigrations
```

가상환경 활성화, 의존성 설치, `.env`, PostgreSQL 실행 여부를 차례로 확인합니다.
