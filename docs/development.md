# 개발 안내

일반 설치에는 소스 빌드가 필요하지 않습니다. 이 문서는 코드를 수정하는 개발자를 위한 안내입니다.

## 코드 구조

Python 표준 HTTP 서버, SQLite, 일반 JavaScript를 사용합니다. 프런트엔드 빌드 도구는 사용하지 않습니다.

| 파일 | 역할 |
| --- | --- |
| `receipt_bridge/admin.py`, `auth.py` | 웹 API, 설정 저장, 인증·세션 |
| `receipt_bridge/store.py` | DB 조회와 작업 기록 |
| `receipt_bridge/config.py` | 설정값과 검증 |
| `receipt_bridge/service.py` | 영수증 처리 단계와 재시도 |
| `receipt_bridge/images.py` | 이미지 보정·OCR |
| `receipt_bridge/ai.py`, `runner.py` | AI 연결과 CLI 실행 |
| `receipt_bridge/ledger.py`, `messenger.py` | 가계부·Telegram 연결 |
| `receipt_bridge/static/` | 웹 화면·스타일·아이콘 |

`settings.js`는 `app.js`보다 먼저 로드합니다. HTTP 응답 형식, 설정 키, DB 상태, 거래 중복 방지 키의 호환성을 유지하세요. 접속 키를 로그나 일반 응답에 포함하지 않습니다.

## 테스트

저장소 폴더에서 실행합니다. 실제 접속 키는 필요하지 않습니다.

```bash
# Python 테스트
docker compose -f compose.test.yaml run --build --rm test -q

# 린트·서식 검사
docker compose -f compose.test.yaml run --rm --entrypoint ruff test check --no-cache receipt_bridge tests
docker compose -f compose.test.yaml run --rm --entrypoint ruff test format --no-cache --check receipt_bridge tests

# 화면 테스트·JavaScript 구문 검사
docker compose -f compose.test.yaml --profile ui run --build --rm ui-test

# 실행 이미지 빌드
docker compose -f compose.yaml -f compose.build.yaml build receipt-bridge
```

테스트 실행은 네트워크를 차단하며 임시 DB와 외부 서비스 대역을 사용합니다. 이미지 빌드에는 패키지를 내려받을 인터넷 연결이 필요합니다. 실제 영수증·접속 정보·운영 DB를 연결하지 않습니다.

## 운영과 분리된 개발 서비스

개발 가계부가 실행 중이고 해당 Docker 네트워크에 연결하는 구성을 기준으로 합니다. 네트워크 이름이 다르면 `.env.dev`의 `RECEIPT_BRIDGE_DEV_LEDGER_NETWORK`를 변경하세요. 가계부에 도메인·서버 IP로 연결한다면 `compose.dev.yaml`의 추가 `ledger-dev` 네트워크 연결과 최상위 선언을 제거할 수 있습니다.

```bash
cp .env.dev.example .env.dev
cp config.dev.example.toml config.dev.toml
chmod 600 .env.dev
docker compose --env-file .env.dev -f compose.dev.yaml up -d --build
```

기존 파일이 있다면 복사해 덮어쓰지 마세요.

- 프로젝트·컨테이너: `receipt-bridge-dev`
- 기본 접속: `http://127.0.0.1:18089/`
- 데이터 볼륨: `receipt-bridge-dev-data`
- 기본 가계부 네트워크: `duet-ledger-dev_default`

첫 접속에서 개발용 관리자 비밀번호를 만듭니다. 웹에서 **개발용 봇·가계부 주소·앱 비밀번호·계좌**를 설정합니다. 운영용 키나 DB는 복사하지 않습니다. 같은 봇을 운영·개발에서 동시에 사용하면 수신이 충돌합니다.

다른 PC에서 접근해야 한다면 `.env.dev`의 바인딩 주소를 신뢰하는 내부망 IP로 변경합니다. 개발 화면을 인터넷에 공개하지 마세요.

갱신·로그·중지는 같은 파일과 프로젝트를 사용합니다.

```bash
docker compose --env-file .env.dev -f compose.dev.yaml up -d --build
docker compose --env-file .env.dev -f compose.dev.yaml logs --tail=100 receipt-bridge
docker compose --env-file .env.dev -f compose.dev.yaml stop
```

**`down -v`는 개발 DB·원본을 삭제합니다.** `compose.build.yaml`은 기본 설치와 같은 데이터를 사용하므로, 운영과 개발을 동시에 실행하려면 `compose.dev.yaml`을 사용하세요.
