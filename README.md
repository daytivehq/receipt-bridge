# Receipt Bridge

Telegram으로 보낸 영수증 사진을 AI로 읽고 [Duet Ledger](https://github.com/daytivehq/duet-ledger)에 거래와 사진을 저장하는 서비스입니다.

사진 수신 → 원본 보관·보정 → AI 분석 → Telegram에서 확인·수정 → 가계부 저장 순서로 처리합니다. 기본값은 **확인 후 저장**입니다.

- 대시보드, 작업 내역, 로그 검색, 서비스 설정 화면을 제공합니다.
- Ollama, Codex CLI, Claude Code CLI, Antigravity CLI를 선택할 수 있습니다.
- 재시작 후 작업을 이어서 처리하고, 거래 저장 후 사진 첨부만 실패하면 첨부만 재시도합니다.
- 사진 한 장에 영수증 하나를 지원합니다. 메신저 연결은 현재 Telegram만 지원합니다.

## Docker로 설치

Docker Engine과 Compose 플러그인, Duet Ledger, Telegram 봇, 사용할 AI가 필요합니다. 이미지에는 AI 모델이 포함되어 있지 않습니다. AMD64·ARM64를 지원합니다.

아래 구성은 **0.1.1 이상 이미지**에서 사용할 수 있습니다. 별도 `.env`나 설정 파일 없이 시작합니다.

1. 설치 폴더를 만듭니다.

   ```bash
   mkdir receipt-bridge
   cd receipt-bridge
   ```

2. 아래 내용을 `compose.yaml`로 저장합니다. Docker 관리 도구를 사용한다면 Compose 입력란에 붙여넣어도 됩니다.

   ```yaml
   name: receipt-bridge
   services:
     receipt-bridge:
       container_name: receipt-bridge
       image: ghcr.io/daytivehq/receipt-bridge:latest
       restart: unless-stopped
       ports:
         - "8892:8092"
       volumes:
         - receipt-data:/data
       mem_limit: 2g
   volumes:
     receipt-data:
   ```

3. 실행합니다.

   ```bash
   docker compose pull
   docker compose up -d
   ```

4. **http://서버주소:8892/** 에 접속해 관리자 비밀번호를 만듭니다. 같은 컴퓨터에서는 http://127.0.0.1:8892/ 를 사용합니다.

포트를 바꾸려면 `8892:8092`에서 앞의 숫자만 바꾸세요. **첫 접속자가 관리자 비밀번호를 설정하므로, 초기 설정은 신뢰하는 네트워크에서 진행하세요.** 인터넷에서 접근하려면 HTTPS와 접근 제한을 구성하세요.

## 연결 설정

웹의 **서비스 설정**에서 다음 값을 입력합니다. 부족한 항목은 화면에서 안내합니다.

| 구분 | 입력할 값 |
| --- | --- |
| 가계부 | `/api/v1`로 끝나는 API 주소, 앱 비밀번호 |
| Telegram | 봇 토큰, 허용 사용자 ID·채팅 ID, 저장할 계좌 ID |
| AI | 제공자, 모델 이름, 해당 AI 서버 주소 |

- 가계부 주소 예: `https://ledger.example.com/api/v1`. 앱 비밀번호에는 필요한 계좌의 `read`, `create`, `receipts` 권한만 부여합니다.
- Telegram 사용자 ID는 사람 번호, 채팅 ID는 대화방 번호, 계좌 ID는 가계부 계좌를 구분하는 고유 ID입니다. 확인 방법은 [운영 안내](docs/operations.md#id-확인)를 참고하세요.
- 컨테이너 안의 `127.0.0.1`은 컨테이너 자신입니다. 다른 서비스에 연결하는 방법은 [주소 설정](docs/compose.md#연결-주소)을 참고하세요.
- CLI 방식의 AI는 별도 분석 컨테이너가 필요합니다. [AI 연결 안내](docs/ai-providers.md)를 따라 준비하세요.

자동 저장은 끈 상태로 테스트 계좌와 테스트 영수증을 사용하세요. 대시보드에서 처리를 재개하고 사진을 보낸 뒤 결과를 확인합니다. **확인·저장을 누르면 실제 거래가 생성됩니다.**

## 업데이트

먼저 [데이터를 백업](docs/operations.md#백업복원)한 뒤 설치 폴더에서 실행합니다.

```bash
docker compose pull receipt-bridge
docker compose up -d receipt-bridge
```

화면 하단에서 실행 버전을 확인할 수 있습니다. `latest`는 최근 발행된 정식 이미지이며, 자동으로 업데이트되지는 않습니다.

**기존 설치를 바꿀 때는 데이터 볼륨과 프로젝트 이름을 유지하세요. `docker compose down -v`는 DB와 원본 사진을 삭제합니다.**

## 더 알아보기

- [운영 안내](docs/operations.md): ID 확인, 로그, 재시도, 백업·복원, 원격 접속.
- [Compose 설정](docs/compose.md): 파일 선택, 각 옵션의 뜻, 연결 주소.
- [AI 연결](docs/ai-providers.md): Ollama와 CLI 분석 설정.
- [개발 안내](docs/development.md): 개발 환경과 테스트.
- [이미지 발행](docs/publishing.md): 저장소 관리자를 위한 릴리즈 절차.

DB에는 접속 키가 평문으로 저장됩니다. 원본 사진·DB·백업은 비공개로 보관하고 백업 저장소를 암호화하세요. 실제 설정 파일과 데이터는 Git에 올리지 않습니다.
