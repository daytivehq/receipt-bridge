# 코드 구조와 검증

이 서비스는 Python 표준 HTTP 서버, SQLite, 일반 JavaScript로 구성합니다. 프런트엔드 빌드 도구나 추가 프레임워크는 사용하지 않습니다.

## 변경할 코드 찾기

| 변경 대상 | 파일과 책임 |
| --- | --- |
| 웹 요청·응답, 세션·인증 | `receipt_bridge/admin.py`: HTTP 경로 선택, 로그인, 작업 상세·이미지 응답 |
| 웹 설정 저장 | `AdminState`: 입력·접속 키 검증, 실행 중 작업을 보호하는 변경 제한, 설정 저장 |
| DB 조회·영구 기록 | `receipt_bridge/store.py`: SQL·트랜잭션·목록 페이지 조회. 화면 코드에서 SQL을 실행하지 않음 |
| 설정값·접속 키 이름 | `receipt_bridge/config.py`: 설정 모델, 공통 접속 키 이름 `CREDENTIAL_FIELDS` |
| 화면 공통 요소·대시보드·로그·작업 상세 | `receipt_bridge/static/app.js` |
| 서비스 설정 화면 | `receipt_bridge/static/settings.js`: 항목 정의, 카드 구성, AI 표시 전환, 입력 해석, 저장 처리 |
| 영수증 처리 단계·재시도 | `receipt_bridge/service.py` |
| AI·가계부·메신저 연결 | `ai.py`, `ledger.py`, `messenger.py` |

설정 화면은 표시 문구 대신 `settingsSections`의 `key`로 영역을 구분합니다. AI 제공자 이름과 입력 안내는 `AI_PROVIDERS`에서 함께 관리합니다. 설정값 해석은 `parseSettingValue`, 요청 구성은 `settingsPayload`, 저장 동작은 `bindSettingsSave`로 나눕니다.

`settings.js`를 `app.js`보다 먼저 `defer`로 로드합니다. 두 파일은 브라우저의 일반 스크립트이며 공통 화면 함수와 상태를 공유합니다. UI 테스트도 HTML에 적힌 순서대로 두 스크립트를 실행합니다. JavaScript 파일을 추가하면 서버의 정적 파일 목록과 HTML 로딩 목록을 함께 수정해야 합니다.

## 유지할 호환성

- 기존 HTTP 경로·응답 필드·오류 상태 코드·세션/CSRF 규칙.
- 설정 키·DB 스키마·작업 상태·페이지 크기와 정렬 순서.
- 거래 생성 요청 본문과 Idempotency-Key의 재사용, 사진 첨부만 재시도하는 동작.
- 접속 키를 기본 응답과 로그에 포함하지 않는 원칙. 보기 버튼의 명시적 인증 요청만 원문을 반환.
- SQL 공통 페이지 함수의 테이블·필드·정렬은 코드에 고정된 값만 전달. 검색값은 SQL 매개변수로 전달.

## Docker로 개발 검증

아래 명령은 개발자용입니다. 일반 설치·운영에는 필요하지 않습니다.

```bash
# Python 테스트: 임시 DB와 외부 서비스 대역 사용, 네트워크 차단
docker compose -f compose.test.yaml run --build --rm test -q

# Python 린트·서식 검사
docker compose -f compose.test.yaml run --rm --entrypoint ruff test check --no-cache receipt_bridge tests
docker compose -f compose.test.yaml run --rm --entrypoint ruff test format --no-cache --check receipt_bridge tests

# 화면 테스트·JavaScript 구문 검사
docker compose -f compose.test.yaml --profile ui run --build --rm ui-test

# 운영 이미지 빌드
docker compose build receipt-bridge
```

Python·OCR·Node.js 도구는 컨테이너에서 실행합니다. UI 이미지 빌드 시 npm 패키지 설치에 인터넷이 필요하며, 테스트 실행은 네트워크를 차단합니다. 호스트의 node_modules나 서비스 접속 정보는 연결하지 않습니다. 테스트용 데이터와 연결 대역은 `tests/fakes.py`에만 두며 운영 패키지에는 포함하지 않습니다.
