# 우빈 주식 Terminal

개인 관심종목을 정리하고, 섹터/테마 흐름과 종목 상세 정보를 한 화면에서 보기 위한 주식 대시보드입니다.

이 프로젝트는 투자 판단을 대신하지 않습니다. 가격, 지표, 뉴스는 지연·누락·오류가 있을 수 있으니 실제 매수/매도 전에는 증권사, 공시, 실적 자료를 다시 확인해야 합니다.

## 주요 기능

- 섹터·테마 히트맵
- Part별 YTD/1D 흐름
- 종목 트리뷰와 종목 상세 화면
- 종목 검색 및 직접 추가
- 관심종목 등록
- 현재가, 1D, PER, PBR, ROE, Forward PE, 목표가 평균, 52주 위치 표시
- 가격 차트와 기간 선택
- 차트 구간 선택 시 등락률 표시
- GPT 없이 동작하는 차트 분석 코멘트
- 시장/종목 뉴스 카드
- VIX, 원/달러 표시
- 브라우저별 관심종목/직접 추가 종목 저장

## 저장 방식

브라우저별로 따로 저장됩니다.

- 관심종목: 브라우저 localStorage
- 직접 추가한 종목: 브라우저 localStorage
- 기본 종목 데이터: `assets/data.js`
- 화면 코드: `assets/app.js`
- 디자인 코드: `assets/styles.css`
- 로컬 API 서버: `backend/server.py`
- 가격/뉴스/지표 캐시: 로컬 SQLite 파일

즉, A 사용자가 자기 브라우저에서 관심종목을 바꿔도 B 사용자 브라우저에는 영향을 주지 않습니다.

## 실행 방법 1: 화면만 바로 열기

아래 파일을 브라우저에서 열면 기본 화면을 볼 수 있습니다.

```text
index.html
```

이 방식은 백엔드 API 없이 정적 화면만 실행합니다. 일부 현재가/뉴스/지표 갱신 기능은 제한됩니다.

## 실행 방법 2: 로컬 서버로 실행

뉴스, 가격 이력, 외부 지표 연동을 쓰려면 로컬 서버를 켜는 방식이 좋습니다.

PowerShell에서 프로젝트 폴더로 이동한 뒤 실행합니다.

```powershell
cd "프로젝트_폴더_경로"
python .\backend\server.py --host 127.0.0.1 --port 8787
```

이 PC의 Codex 파이썬을 사용할 경우 예시는 아래와 같습니다.

```powershell
cd "C:\Users\dnqls\Documents\Codex\2026-04-30\https-docs-google-com-spreadsheets-d\stock-dashboard-web"
C:\Users\dnqls\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe .\backend\server.py --host 127.0.0.1 --port 8787
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:8787
```

서버를 끄려면 PowerShell 창에서 `Ctrl + C`를 누릅니다.

## 선택 패키지 설치

가격/지표 연동 품질을 높이려면 아래 패키지를 설치합니다.

```powershell
python -m pip install -r .\requirements.txt
```

Codex 파이썬을 사용할 경우:

```powershell
C:\Users\dnqls\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pip install -r .\requirements.txt
```

## API 키 설정

API 키는 브라우저 코드에 직접 넣지 않습니다. 프로젝트 폴더에 `.env` 파일을 만들고 서버가 읽게 합니다.

`.env.example`을 복사해서 `.env`로 만든 뒤 필요한 키만 채웁니다.

```text
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
FMP_API_KEY=
FINNHUB_API_KEY=
ALPHAVANTAGE_API_KEY=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
```

현재 앱은 API 키가 없어도 기본 화면은 열립니다. 다만 외부 지표, 뉴스, AI 요약은 제한될 수 있습니다.

## GitHub 공유 시 주의

아래 파일은 GitHub에 올리면 안 됩니다.

- `.env`
- `_backup...` 폴더
- `backend/*.sqlite3`
- `backend/*.sqlite3-wal`
- `backend/*.sqlite3-shm`
- 서버 로그 파일

이 항목들은 `.gitignore`에 등록되어 있습니다.

## GitHub Pages 배포 주의

GitHub Pages는 HTML/CSS/JS만 실행합니다. Python 백엔드는 실행하지 않습니다.

따라서 GitHub Pages에서는 기본 화면과 브라우저 저장 기능은 가능하지만, 다음 기능은 제한됩니다.

- Python API 서버 기반 가격 갱신
- SQLite 캐시 사용
- 서버에서 읽는 `.env` 기반 API 키 사용
- 외부 뉴스/지표 백엔드 연동

이 기능까지 공유하려면 백엔드를 Render, Railway, Fly.io 같은 별도 서버에 배포해야 합니다.

## 개발 메모

현재 버전은 개인 로컬 사용과 GitHub 코드 공유를 기준으로 정리된 상태입니다. 여러 사람이 각자 관심종목을 다르게 쓰는 것은 브라우저 저장 방식으로 처리합니다.
