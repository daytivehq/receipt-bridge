# 운영 안내

## 화면과 로그

- `/dashboard`: 처리 현황, 일시정지·재개.
- `/jobs`: 작업별 상태·사진·추출 결과·처리 이력.
- `/logs`: 내용·작업 ID·수준·시간 범위 검색. 시간은 서비스 시간대의 24시간 형식입니다.
- `/settings`: 연결·AI·처리 설정. 부족한 항목은 화면에서 안내합니다.

```bash
docker compose ps
docker compose logs --tail=100 receipt-bridge
docker compose --profile cli logs --tail=100 ai-runner
```

비밀번호·토큰은 보기 버튼을 눌렀을 때만 표시합니다. 설정은 다음 작업부터 적용하며 거래 저장이 시작된 작업의 내용은 고정됩니다.

## 사용자·채팅·계좌 ID 확인

Telegram 사용자 ID는 사람 번호, 채팅 ID는 대화방 번호입니다. 개인 대화에서는 보통 같고 그룹 ID는 음수일 수 있습니다. 다른 polling 프로그램과 동시에 조회하지 마세요.

1. `docker compose stop receipt-bridge`로 수신을 멈춥니다.
2. 다음 명령이 토큰 입력을 기다릴 때 본인의 봇에 새 `/start` 메시지를 보냅니다.
3. 토큰을 입력하면 ID만 출력합니다. 토큰은 화면에 표시하지 않습니다.

```bash
docker compose run --rm --no-deps --entrypoint python receipt-bridge -c '
import getpass, httpx
key = getpass.getpass("Telegram 봇 토큰: ")
try:
    with httpx.Client(trust_env=False, timeout=20) as client:
        response = client.post("https://api.telegram.org/bot" + key + "/getUpdates", json={"timeout": 0})
        response.raise_for_status()
        for item in response.json().get("result", []):
            message = item.get("message", {})
            print("사용자:", message.get("from", {}).get("id"), "채팅:", message.get("chat", {}).get("id"))
except Exception:
    print("조회 실패: 토큰과 네트워크를 확인하세요.")
'
docker compose start receipt-bridge
```

중간에 명령을 취소했더라도 마지막 `start` 명령으로 수신을 다시 시작하세요. 결과가 없으면 새 메시지를 보내고 다시 조회합니다.

가계부 계좌 ID는 앱 비밀번호의 `GET /api/v1/accounts` 응답에서 `id`와 `name`을 확인합니다. 가계부 웹의 개발자 도구 → Network → 새로고침 → `accounts` 응답에서도 볼 수 있습니다. 사용자 ID와 계좌 ID는 다릅니다.

## 영수증 수정·재시도

Telegram에서 `/help`로 명령을 확인합니다.

- `/pending`: 대기 작업 목록.
- `/status 작업ID`: 결과 다시 보기.
- `/edit 작업ID amount=12000 date=2026-01-15`: 읽은 내용 수정.
- `/categories 작업ID`: 해당 계좌의 분류 확인.
- `/rotate 작업ID 90`, `/original 작업ID`: 회전·원본 구도로 재분석.
- `/cancel 작업ID`: 저장 시작 전 취소. 원본은 보관합니다.
- `/retry 작업ID`: 실패 단계만 재시도.

첨부만 실패했다면 거래는 이미 저장된 상태입니다. 새 사진을 보내 거래를 다시 만들기보다 기존 작업의 첨부를 재시도하세요. 앱 비밀번호 교체 시 기존 거래 계좌의 `receipts` 권한이 필요합니다.

거래 ID 없이 생성 결과가 불명확한 작업은 자동으로 취소하거나 새 키로 재전송하지 않습니다. Duet Ledger의 중복 방지 범위가 사용자 ID이므로 최초 요청자와 새 키의 사용자가 다르면 중복될 수 있습니다. 기존 거래를 먼저 대조하고 DB 상태를 임의로 지우지 마세요.

## 업데이트

`latest` 이미지를 새로 내려받고 컨테이너를 교체합니다. 먼저 데이터를 백업하세요.

```bash
docker compose pull receipt-bridge
docker compose up -d --no-build receipt-bridge
docker compose ps
docker compose logs --tail=50 receipt-bridge
```

기본 이미지는 `ghcr.io/daytivehq/receipt-bridge:latest`입니다. `docker pull`만 실행하면 이미지만 내려받으며, 실행 중인 서비스는 `up` 명령으로 교체해야 합니다. `latest`는 최근 발행된 정식 릴리즈이며 자동 업데이트 기능은 아닙니다.

`.env`에 이전 버전이 고정되어 있다면 `RECEIPT_BRIDGE_IMAGE=ghcr.io/daytivehq/receipt-bridge:latest`로 변경하세요. 실제 접속 키가 들어 있는 `.env`나 `config.toml`을 예시 파일로 덮어쓰지 마세요. 같은 설치 폴더와 데이터 볼륨을 사용하면 기존 자료를 유지합니다.

### 실행 버전 확인과 버전 고정

화면 하단의 버전을 확인하거나 다음을 실행합니다.

```bash
docker compose exec receipt-bridge python -c 'from receipt_bridge import __version__; print(__version__)'
```

특정 버전으로 고정하려면 `.env`의 `RECEIPT_BRIDGE_IMAGE`를 `ghcr.io/daytivehq/receipt-bridge:0.1.0`처럼 지정하고 위 `pull`·`up` 명령을 실행합니다. 향후 버전에서 DB 형식이 변경될 수 있으므로 이전 버전으로 내리기 전에는 해당 릴리즈의 호환성과 백업을 확인하세요.

### CLI 분석 사용 시

주 서비스만 업데이트하면 기존 ai-runner는 유지됩니다. 릴리즈 안내에서 runner 갱신을 요구하거나 CLI 설치 버전을 변경했을 때는 소스 저장소도 갱신한 뒤 별도로 빌드합니다.

```bash
docker compose --profile cli build ai-runner
docker compose --profile cli up -d --no-build receipt-bridge ai-runner
```

ai-runner는 아직 GHCR에 별도 발행하지 않으므로 `docker pull`로 갱신하지 않습니다. 설치 버전과 인증 설정은 [AI 연결 안내](ai-providers.md)를 참고하세요.

## 백업·복원

DB·원본·접속 키가 함께 필요합니다. 파일 복사 중 DB가 바뀌지 않도록 서비스를 멈춘 상태로 백업합니다.

```bash
mkdir -p backups
chmod 700 backups
docker compose stop receipt-bridge
(umask 077; docker compose run --rm --no-deps --entrypoint tar receipt-bridge -C /data -czf - . > backups/receipt-data.tar.gz)
docker compose start receipt-bridge
```

`.env`, `config.toml`, `secrets/ai-home`도 별도로 안전하게 보관합니다. **백업은 평문입니다. 접근이 제한된 암호화 저장소에 보관하세요.** 보관 기간은 운영자가 정하며 서비스가 자동 삭제하지 않습니다.

복원은 서비스를 중지하고 현재 자료를 별도로 백업한 뒤 수행합니다. 아래 명령은 같은 경로의 파일을 덮어쓰므로 대상과 백업 파일을 확인하세요.

```bash
docker compose stop receipt-bridge
docker compose run --rm -T --no-deps --entrypoint tar receipt-bridge -C /data -xzf - < backups/receipt-data.tar.gz
docker compose start receipt-bridge
```

`docker compose down -v`는 작업 DB와 원본 사진이 든 데이터 볼륨을 삭제합니다.

## 원격 접속과 자원 제한

기본 접속은 서버 로컬에 한정합니다. 원격 PC에서는 다음처럼 SSH 터널을 열고 `http://127.0.0.1:8092/`를 사용합니다.

```bash
ssh -L 8092:127.0.0.1:8092 사용자@서버
```

HTTPS 프록시를 사용한다면 루트 경로 전체를 브리지로 전달하고 `config.toml`의 `web_secure_cookie=true`를 설정합니다. runner 포트는 공개하지 않습니다. 초기 관리자 설정을 마친 후 신뢰하는 사용자에게만 접속을 허용하세요.

브리지 기본 메모리 제한은 2GB이며 `.env`의 `BRIDGE_MEMORY_LIMIT`로 조절합니다. runner는 2GB·동시 연결 8개·AI 실행 1개로 제한합니다. 실제 사진과 모델로 사용량을 확인하세요.
