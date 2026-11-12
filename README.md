# Receipt Bridge

웹에서 올린 영수증 사진이나 Telegram으로 보낸 사진·지출 텍스트를 AI로 읽고 [Duet Ledger](https://github.com/daytivehq/duet-ledger)에 거래와 사진을 저장하는 서비스입니다.

사진·텍스트 수신 → AI 분석 → 웹 또는 Telegram에서 확인·수정 → 가계부 저장 순서로 처리합니다. 사진은 원본 보관·보정을 거칩니다. 기본값은 **확인 후 저장**입니다.

- 사진 업로드, 대시보드, 작업 내역, 로그 검색, 서비스 설정 화면을 제공합니다.
- Ollama, Codex CLI, Claude Code CLI, Antigravity CLI를 선택할 수 있습니다.
- 재시작 후 작업을 이어서 처리하고, 거래 저장 후 사진 첨부만 실패하면 첨부만 재시도합니다.
- 사진 한 장에 영수증 하나를 지원합니다. 여러 사진과 한 메시지의 여러 지출도 각각 처리합니다. 메신저 연결은 현재 Telegram만 지원합니다.

## Docker로 설치

Docker Engine과 Compose 플러그인, Duet Ledger, 사용할 AI가 필요합니다. Telegram 봇은 메신저 입력을 사용할 때만 준비합니다. 이미지에는 AI 모델이 포함되어 있지 않습니다. AMD64·ARM64를 지원합니다.

이 문서는 **0.3.1 기준**입니다. 별도 `.env`나 설정 파일 없이 시작합니다.

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
       image: ${RECEIPT_BRIDGE_IMAGE:-ghcr.io/daytivehq/receipt-bridge:latest}
       restart: unless-stopped
       ports:
         - "${ADMIN_BIND:-127.0.0.1}:${ADMIN_PORT:-8892}:8092"
       environment:
         AI_RUNNER_AUTH_DIR: /runner-auth
         AI_RUNNER_TOKEN: ${AI_RUNNER_TOKEN:-}
       volumes:
         - receipt-data:/data
         - runner-auth:/runner-auth
       mem_limit: 2g

     ai-runner:
       image: ${AI_RUNNER_IMAGE:-ghcr.io/daytivehq/receipt-bridge-ai-runner:latest}
       restart: unless-stopped
       init: true
       environment:
         AI_RUNNER_AUTH_DIR: /runner-auth
         AI_RUNNER_TOKEN: ${AI_RUNNER_TOKEN:-}
       volumes:
         - runner-auth:/runner-auth:ro
         - ai-home:/ai-home
       read_only: true
       tmpfs:
         - /tmp:size=512m,mode=1777
       cap_drop: [ALL]
       security_opt: [no-new-privileges:true]
       mem_limit: 2g
       stop_grace_period: 5m

   volumes:
     receipt-data:
     runner-auth:
     ai-home:
   ```

3. 실행합니다.

   ```bash
   docker compose pull
   docker compose up -d
   ```

4. 서버에서 **http://127.0.0.1:8892/** 에 접속해 관리자 비밀번호를 만듭니다.

기본은 서버 자신에서만 접속할 수 있습니다. 다른 PC에서 사용하려면 설치 폴더에 `.env`를 만들고 `ADMIN_BIND=0.0.0.0`을 입력한 뒤 다시 실행하세요. 이후 `http://서버주소:8892/`로 접속합니다. Docker 관리 도구에서는 환경변수로 지정하거나 `ports`를 `"8892:8092"`로 바꿀 수 있습니다. 포트 변경은 `ADMIN_PORT`로 지정합니다. SSH·HTTPS 접속 방법은 [운영 안내](docs/operations.md#원격-접속)를 참고하세요.

**첫 접속자가 관리자 비밀번호를 설정하므로, 초기 설정은 신뢰하는 네트워크에서 진행하세요.** 인터넷에서 접근하려면 HTTPS와 접근 제한을 구성하세요.

## 연결 설정

웹의 **서비스 설정**에서 다음 값을 입력합니다. 부족한 항목은 화면에서 안내합니다.

| 구분 | 입력할 값 |
| --- | --- |
| 가계부 | `/api/v1`로 끝나는 API 주소, 앱 비밀번호 |
| Telegram (선택) | 봇 토큰, 허용 사용자 ID·채팅 ID, 저장할 계좌 ID |
| AI | 제공자, 모델 이름, 해당 AI 서버 주소 |

- 가계부 주소 예: `https://ledger.example.com/api/v1`. 앱 비밀번호에는 필요한 계좌의 `read`, `create`, `receipts` 권한만 부여합니다.
- Telegram 사용자 ID는 사람 번호, 채팅 ID는 대화방 번호, 계좌 ID는 가계부 계좌를 구분하는 고유 ID입니다. 확인 방법은 [운영 안내](docs/operations.md#id-확인)를 참고하세요.
- 컨테이너 안의 `127.0.0.1`은 컨테이너 자신입니다. 다른 서비스에 연결하는 방법은 [주소 설정](docs/compose.md#연결-주소)을 참고하세요.
- CLI 분석 서비스는 Compose에 포함되어 자동으로 시작합니다. 제공자·모델·시간 제한은 웹에서 설정하며 토큰 입력이나 별도 빌드는 필요 없습니다. 최초 계정 인증은 [AI 연결 안내](docs/ai-providers.md)를 참고하세요.

처음에는 테스트 계좌와 테스트 영수증으로 확인하세요. 처리가 일시정지되어 있다면 대시보드에서 재개합니다. 웹 업로드는 항상 확인 후 저장하며, Telegram의 자동 저장은 처음에는 꺼 두세요. **확인·저장을 누르면 실제 거래가 생성됩니다.**

## 웹에서 사진 업로드

1. 왼쪽 메뉴의 **사진 업로드**를 엽니다.
2. 가계부 계좌를 선택하고 영수증 사진을 최대 20장까지 고릅니다. 설명도 함께 입력할 수 있습니다.
3. **분석 시작 → 처리 결과 보기**를 누릅니다.
4. 내용을 확인하고 필요하면 수정한 뒤 **확인·저장**을 누릅니다.

거래 생성과 보정 사진 첨부가 함께 진행됩니다. 사진 첨부만 실패했다면 작업 상세에서 첨부만 재시도할 수 있습니다. 웹 업로드는 Telegram 설정 없이 사용할 수 있으며, 웹에서 올린 사진의 결과를 Telegram으로 전송하지 않습니다. 여러 사진에 입력한 설명은 각 사진에 동일하게 적용합니다.

웹 사진 한도는 서비스 설정 → 공통 처리와 재시도에서 **1~100MB**로 정합니다. 기본값은 20MB이며, 사진은 4천만 화소 이하여야 합니다. 큰 사진은 메모리·저장 공간을 더 사용합니다. Telegram 봇의 다운로드는 별도로 최대 20MB입니다.

저장 계좌는 가계부 API에서 조회합니다. 목록이 나오지 않으면 화면의 연결 오류를 확인하고, 설정을 고친 뒤 **계좌 다시 불러오기**를 누르세요. `duet-ledger` 같은 주소는 두 서비스가 같은 Docker 네트워크에 있어야 합니다. 다른 네트워크에서는 접속 가능한 가계부 도메인 또는 서버 IP·공개 포트를 사용하세요.

받은 원본은 영수증 서비스에 보관합니다. 회전·영역 자르기·원근·밝기 보정을 거친 사진은 **JPG, 최대 5MB·1,600만 화소**로 줄여 가계부에 첨부합니다. 숫자나 내용을 새로 그리지 않으며, WebP로 변환하지 않습니다. 보정이 실패하면 원본 구도로 JPG를 만들고 확인을 요청합니다.

## Telegram 입력 예시

| 보내는 내용 | 처리 방법 |
| --- | --- |
| 영수증 사진 5장 | 사진별로 차례로 분석하고 각각 확인·저장 |
| 사진과 함께 `이건 식비야` | 사진을 읽고 설명의 분류 등을 반영 |
| `오늘 AA에서 5000원 썼어` | 사진 없는 거래로 분석 |
| `나 오늘 AA에서 5000원, BB에서 43,500원 썼어` | 두 거래로 나누어 각각 확인·저장 |

텍스트 한 메시지는 최대 20건입니다. 날짜는 `오늘`·`어제` 또는 `2026-11-05`처럼 입력하세요. `오늘`은 메시지를 보낸 날짜를 기준으로 합니다. 금액·날짜·분류가 불명확하면 수정해야 저장할 수 있습니다. 텍스트 거래와 사진 설명이 있는 거래는 자동 저장하지 않습니다.

사진과 설명의 금액·날짜가 다르면 웹의 거래 정보 수정 또는 `/edit`로 사용할 값을 선택해야 합니다. 앨범 설명은 해당 설명이 붙은 사진에만 적용합니다. 텍스트만 보낸 거래는 사진 첨부를 생략합니다. 자세한 수정 명령은 [운영 안내](docs/operations.md#수정재시도)를 참고하세요.

## 업데이트

먼저 [데이터를 백업](docs/operations.md#백업복원)한 뒤 설치 폴더에서 실행합니다.

```bash
docker compose pull
docker compose up -d
```

영수증 서비스와 분석 서비스 이미지를 함께 업데이트합니다. 화면 하단에서 실행 버전을 확인할 수 있습니다. `latest`는 최근 발행된 정식 이미지이며, 자동으로 업데이트되지는 않습니다.

**기존 설치를 바꿀 때는 데이터 볼륨과 프로젝트 이름을 유지하세요. `docker compose down -v`는 DB와 원본 사진을 삭제합니다.**

## 더 알아보기

- [운영 안내](docs/operations.md): ID 확인, 로그, 재시도, 백업·복원, 원격 접속.
- [Compose 설정](docs/compose.md): 파일 선택, 각 옵션의 뜻, 연결 주소.
- [AI 연결](docs/ai-providers.md): Ollama와 CLI 분석 설정.
- [개발 안내](docs/development.md): 개발 환경과 테스트.
- [이미지 발행](docs/publishing.md): 저장소 관리자를 위한 릴리즈 절차.

DB에는 가계부·Telegram 접속 키가, 분석 전용 볼륨에는 AI 인증 정보가 저장됩니다. 모두 평문으로 취급하세요. 원본 사진·DB·백업은 비공개로 보관하고 백업 저장소를 암호화하세요. 실제 설정 파일과 데이터는 Git에 올리지 않습니다.
