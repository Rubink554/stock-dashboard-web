# GitHub 공유 전 체크리스트

## 올려도 되는 핵심 파일

- `index.html`
- `assets/app.js`
- `assets/styles.css`
- `assets/data.js`
- `backend/*.py`
- `backend/data_sources/*.py`
- `README.md`
- `NEXT_STEPS.md`
- `requirements.txt`
- `.env.example`
- `.gitignore`

## 올리면 안 되는 파일

- `.env`
- API 키가 적힌 메모 파일
- `_backup...` 폴더
- `backend/*.sqlite3`
- `backend/*.sqlite3-wal`
- `backend/*.sqlite3-shm`
- `backend/*.log`
- `__pycache__` 폴더

## 공유받는 사람이 알아야 할 점

- 브라우저에서 `index.html`을 바로 열면 기본 화면은 볼 수 있습니다.
- `http://127.0.0.1:8787` 방식은 각자 PC에서 Python 서버를 켜야 합니다.
- API 키는 각자 `.env` 파일에 넣어야 합니다.
- 관심종목/직접 추가 종목은 각자 브라우저에 따로 저장됩니다.
- GitHub Pages는 Python 서버를 실행하지 않으므로 API 기능은 제한됩니다.

## 업로드 전 확인

PowerShell에서 아래처럼 확인합니다.

```powershell
Get-ChildItem -Force
```

아래 항목이 GitHub 업로드 목록에 보이면 제외해야 합니다.

```text
.env
_backup...
backend\woobin_stock.sqlite3
backend\woobin_stock.sqlite3-wal
backend\woobin_stock.sqlite3-shm
```
