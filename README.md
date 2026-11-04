# Receipt Bridge

Telegram에 올린 영수증 사진을 읽어 [Duet Ledger](https://github.com/daytivehq/duet-ledger)에 거래와 사진을 저장하는 홈서버용 서비스입니다.

사진 수신 → 원본 보관·보정 → AI 분석 → Telegram에서 확인·수정 → 가계부 저장 순서로 처리합니다. 기본값은 **사용자 확인 후 저장**입니다.

## 지원 기능

- Telegram 사진·이미지 파일 수신. 공개 수신 주소 없이 long polling으로 연결합니다.
- Ollama, Codex CLI, Claude Code CLI, Antigravity CLI 선택. Antigravity는 로컬 OCR 텍스트를 분석합니다.
- 대시보드, 작업 내역, 시간 범위 로그 검색, 서비스 설정 화면.
- 재시작 후 작업 재개, 메시지 중복 방지, 거래 생성 요청 재사용, 사진 첨부만 재시도.

현재 버전은 **0.1.0**입니다. 사진 한 장에 영수증 하나를 지원하며, Slack·Discord 연결과 개별 사용자 로그인은 지원하지 않습니다.

## Docker로 시작하기

Docker Engine과 Compose 플러그인, 접속 가능한 Duet Ledger, Telegram 봇, 사용할 AI가 필요합니다. 브리지와 AI 모델은 별도이며 AI 모델은 직접 준비합니다.

저장소를 클론하고 프로젝트 폴더에서 실행하세요. 호스트에 Python이나 Node.js를 별도로 설치할 필요는 없습니다.

```bash
git clone https://github.com/daytivehq/receipt-bridge.git
cd receipt-bridge
cp .env.example .env
cp config.example.toml config.toml
chmod 600 .env
docker compose up -d --build
```

브라우저에서 **http://127.0.0.1:8092/**를 열고 첫 관리자 비밀번호를 만듭니다. `ADMIN_PORT`로 호스트 포트를 바꿀 수 있습니다.

다른 PC에서 접근하려면 SSH 터널을 사용하거나 HTTPS 역방향 프록시를 구성하세요. 기본 Compose는 서버 자신의 로컬 주소에서만 접속할 수 있습니다.

서비스 설정에서 다음을 입력합니다.

| 구분 | 필요한 값 |
| --- | --- |
| 가계부 연결 | `/api/v1`로 끝나는 API 주소, 앱 비밀번호 |
| Telegram 연결 | BotFather에서 받은 봇 토큰, 허용 사용자 ID·채팅 ID, 저장 계좌 ID |
| AI 분석 | 제공자, 모델 이름, 해당 AI 서버 주소 |

가계부 앱 비밀번호는 필요한 계좌에만 `read`, `create`, `receipts` 권한을 부여하세요. 일반 로그인 비밀번호와 다릅니다.

Telegram 사용자 ID는 **사람 번호**, 채팅 ID는 **대화방 번호**, 계좌 ID는 **가계부 계좌의 고유 ID**입니다. 사용자별 저장 계좌에는 `Telegram사용자ID = 가계부계좌ID`로 입력합니다. 지정된 계좌에만 등록할 수 있습니다.

컨테이너 내부의 `127.0.0.1`은 컨테이너 자신입니다. 호스트에 설치한 가계부나 Ollama에는 `host.docker.internal:실제포트`를 사용하세요. 별도 Compose의 서비스 이름은 네트워크를 공유하지 않으면 연결되지 않습니다.

## AI 연결

처음에는 Ollama 또는 익숙한 제공자를 선택하고 자동 저장을 끈 상태로 테스트하세요. CLI 제공자는 전용 runner 컨테이너의 설치·인증이 추가로 필요합니다.

설정과 제공자별 제한은 [AI 연결 안내](docs/ai-providers.md)를 참고하세요. 다른 AI로 자동 우회 전송하지 않습니다.

## 첫 영수증 테스트

1. Duet Ledger에 테스트 계좌를 만들고 그 계좌만 허용한 앱 비밀번호를 발급합니다.
2. 서비스 설정의 누락 항목을 모두 채웁니다.
3. 대시보드에서 처리를 재개하고 허용된 Telegram 대화방에 테스트 영수증을 보냅니다.
4. 보정 사진·금액·날짜·분류를 확인합니다. **확인·저장 버튼을 누르면 실제 거래가 생성됩니다.**

## 운영과 보안

- [운영 안내](docs/operations.md): ID 확인, 로그, 재시도, 업데이트, 백업·복원, 원격 접속.
- [개발 안내](docs/development.md): 코드 구조와 테스트 명령.

DB·원본 사진·접속 키는 Docker 데이터 볼륨에 보관합니다. **DB와 백업은 평문이므로 비공개로 보관하고 백업 저장소를 암호화하세요.** `.env`, `config.toml`, `secrets/`, 데이터·백업은 Git에 포함하지 않습니다.

거래 ID가 있는 첨부 실패 작업은 앱 비밀번호 교체 후 첨부만 재시도할 수 있습니다. **거래 생성 결과가 불명확하고 거래 ID가 없는 작업은 키 교체가 제한됩니다.** 작업 상태를 지워 재접수하면 중복 거래가 생길 수 있으므로 기존 거래부터 확인하세요.

0.1.x에서는 확인 후 저장을 기본으로 운영하고, 복구 기능과 실제 AI별 검증을 보강합니다. AI 계정 로그인과 모델 품질은 각 운영 환경에서 확인해야 합니다.
