# 운영 안내

이 문서의 명령은 설치 폴더의 `compose.yaml`을 기준으로 합니다. 다른 파일을 사용한다면 명령에 `-f 파일이름`을 추가하세요.

## 화면과 로그

| 화면 | 할 수 있는 일 |
| --- | --- |
| `/dashboard` | 처리 현황 확인, 일시정지·재개 |
| `/upload` | 사진 업로드·저장 계좌 선택 |
| `/jobs` | 작업 상태·분석 결과 확인, 수정·저장·취소·재시도 |
| `/logs` | 내용·작업 ID·수준·시간 범위로 검색 |
| `/settings` | 연결·AI·처리 설정 변경 |

로그 시간은 서비스에 설정한 시간대의 24시간 형식입니다. 실행 상태와 Docker 로그는 다음으로 확인합니다.

```bash
docker compose ps
docker compose logs --tail=100 receipt-bridge
```

설정은 다음 작업부터 적용됩니다. 거래 저장이 시작된 작업은 저장 내용을 유지합니다.

## ID 확인

Telegram 사용자 ID는 사람 번호, 채팅 ID는 대화방 번호입니다. 개인 대화에서는 같을 수 있고, 그룹 채팅 ID는 음수일 수 있습니다.

1. 아래 첫 명령으로 서비스를 잠시 중지합니다.
2. 본인의 봇에 새 `/start` 메시지를 보냅니다.
3. 조회 명령에서 봇 토큰을 입력하면 ID가 표시됩니다. 토큰은 화면에 표시하지 않습니다.
4. 마지막 명령으로 서비스를 다시 시작합니다.

```bash
docker compose stop receipt-bridge
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

결과가 없으면 새 메시지를 보내고 다시 조회합니다. 같은 봇을 다른 수신 프로그램과 동시에 사용하지 마세요. 중간에 취소했더라도 마지막 `start` 명령은 실행합니다.

웹 업로드는 저장 계좌를 목록에서 고르므로 계좌 ID를 직접 입력하지 않습니다. Telegram 계좌 연결에 필요한 **계좌 ID**는 `GET /api/v1/accounts` 응답의 `id`와 `name`을 확인합니다. 가계부 웹에서도 브라우저 개발자 도구 → Network → 새로고침 → `accounts` 응답으로 확인할 수 있습니다. 계좌 ID와 Telegram 사용자 ID는 다릅니다.

## 수정·재시도

웹에서는 작업 상세의 **거래 정보 수정·확인·저장·취소·실패 단계 재시도**를 사용합니다. 처리 중인 상세 화면은 자동 갱신합니다. 저장을 시작한 거래는 수정·취소할 수 없습니다. Telegram에서 받은 작업도 웹에서 처리할 수 있습니다.

분석 결과가 전혀 없어도 **거래 정보 직접 입력**을 사용할 수 있습니다. 아는 항목만 먼저 저장하고 나머지는 나중에 채워도 됩니다. 빈 금액·날짜는 자동으로 채우지 않습니다. 사진을 내려받지 못한 작업은 먼저 실패 단계 재시도로 사진을 준비해야 최종 저장할 수 있습니다.

Telegram에서는 **정보 입력·수정**을 누르고 안내하는 항목만 보내세요. 금액은 `5,000원`, 분류는 이름이나 코드로 입력할 수 있습니다. `/stop`은 입력 대화만 종료하며 영수증을 취소하지 않습니다. 새 지출을 보내려면 먼저 입력 대화를 종료하세요. 15분이 지나거나 해당 작업이 다른 곳에서 수정되면 입력 대화를 다시 시작해야 합니다.

사진 여러 장은 각각 접수하고 차례로 분석합니다. 한 텍스트의 여러 지출도 작업 ID별로 확인·수정·취소합니다. 한 건을 확인해도 다른 건은 자동 저장되지 않습니다.

사진 설명의 금액·날짜가 사진과 다르면 불일치 안내가 표시됩니다. `/edit 작업ID amount=5000` 또는 `/edit 작업ID date=2026-11-05`로 선택한 값을 입력해야 저장할 수 있습니다. 텍스트 원문·사진 설명은 작업 상세에서도 확인할 수 있습니다.

Telegram에서 `/help`를 보내 명령을 확인합니다.

| 명령 | 기능 |
| --- | --- |
| `/pending` | 대기 작업 목록 |
| `/status 작업ID` | 처리 결과 확인 |
| `/edit 작업ID amount=12000 date=2026-01-15` | 금액·날짜 수정 |
| `/categories 작업ID` | 저장 계좌의 분류 확인 |
| `/rotate 작업ID 90` | 사진 회전 후 재분석 |
| `/original 작업ID` | 원본 구도로 재분석 |
| `/stop` | 정보 입력 대화 종료. 영수증 유지 |
| `/cancel 작업ID` | 저장 시작 전 취소. 원본은 보관 |
| `/retry 작업ID` | 실패한 단계 재시도 |

**첨부만 실패했다면 거래는 이미 저장되었습니다.** 사진을 다시 보내기보다 기존 작업을 재시도하세요. 앱 비밀번호를 바꿨다면 기존 거래 계좌의 `receipts` 권한이 필요합니다.

거래 생성 결과가 불명확하고 거래 ID가 없는 작업은 가계부에서 기존 거래부터 확인합니다. DB 상태를 지우거나 다른 사용자의 앱 비밀번호로 새로 등록하면 중복될 수 있습니다. 이때 앱 비밀번호 변경이 제한될 수 있습니다.

## 업데이트·버전 확인

먼저 데이터를 백업하고 실행합니다.

```bash
docker compose pull
docker compose up -d --no-build
docker compose logs --tail=50 receipt-bridge
```

`docker pull`은 이미지만 받습니다. 실행 중인 서비스는 `up` 명령으로 교체해야 합니다. 화면 하단에서 버전을 확인하거나 다음 명령을 실행합니다.

```bash
docker compose exec receipt-bridge python -c 'from receipt_bridge import __version__; print(__version__)'
```

특정 버전을 쓰려면 두 서비스의 `image` 끝을 `:latest`에서 같은 버전으로 바꿉니다. 예: `:0.3.2`. 저장소 기본 구성은 `.env`의 `RECEIPT_BRIDGE_IMAGE`와 `AI_RUNNER_IMAGE`로 지정할 수도 있습니다. 이전 버전으로 내릴 때는 릴리즈의 DB 호환성과 백업을 먼저 확인하세요.

같은 프로젝트 이름과 데이터 볼륨을 유지합니다. 파일이나 설치 위치를 바꾼다면 [기존 설치 유지](compose.md#기존-설치-유지)를 먼저 확인하세요. 기존 `.env`·`config.toml`을 예시 파일로 덮어쓰지 않습니다.

CLI 분석 컨테이너도 함께 내려받아 교체합니다. 소스 빌드는 필요 없습니다.

## 백업·복원

데이터 볼륨에는 DB·원본 사진·접속 키가 함께 들어 있습니다. 서비스를 멈추고 백업합니다.

```bash
mkdir -p backups
chmod 700 backups
docker compose stop
(umask 077; docker compose run --rm -T --no-deps --entrypoint tar receipt-bridge -C /data -czf - . > backups/receipt-data.tar.gz)
(umask 077; docker compose run --rm -T --no-deps --entrypoint tar receipt-bridge -C /runner-auth -czf - . > backups/runner-auth.tar.gz)
(umask 077; docker compose run --rm -T --no-deps --entrypoint tar ai-runner -C /ai-home -czf - . > backups/ai-home.tar.gz)
docker compose start
```

같은 이름으로 다시 백업하면 이전 백업을 덮어씁니다. 필요한 파일은 날짜별로 보관하세요. 세 파일은 가계부 자료·자동 통신 토큰·AI 로그인 정보입니다. 별도로 사용하는 `.env`·`config.toml`·기존 인증 폴더도 안전하게 백업합니다. **백업은 평문이므로 비공개 암호화 저장소에 보관하세요.** 서비스는 사진과 작업 기록을 자동 삭제하지 않습니다.

복원은 현재 데이터를 먼저 별도 백업한 뒤 진행합니다. **다음 명령은 같은 경로의 파일을 덮어씁니다.**

```bash
docker compose stop
docker compose run --rm -T --no-deps --entrypoint tar receipt-bridge -C /data -xzf - < backups/receipt-data.tar.gz
docker compose run --rm -T --no-deps --entrypoint tar receipt-bridge -C /runner-auth -xzf - < backups/runner-auth.tar.gz
docker compose run --rm -T --no-deps --entrypoint tar ai-runner -C /ai-home -xzf - < backups/ai-home.tar.gz
docker compose start
```

**`docker compose down -v`는 데이터 볼륨의 DB와 원본 사진을 삭제합니다.**

## 원격 접속

로컬에서만 열려면 Compose 포트를 `127.0.0.1:8892:8092`로 제한합니다. 다른 PC에서는 SSH 터널로 연결할 수 있습니다.

```bash
ssh -L 8892:127.0.0.1:8892 사용자@서버
```

이후 해당 PC에서 `http://127.0.0.1:8892/`로 접속합니다. 설치 포트가 다르면 숫자를 바꾸세요.

HTTPS 프록시는 사이트 루트 경로 전체를 앱으로 전달합니다. `config.example.toml`을 복사해 `config.toml`을 만들고 `web_secure_cookie = true`로 설정한 뒤 서비스의 `volumes`에 다음을 추가합니다.

```yaml
- ./config.toml:/app/config.toml:ro
```

컨테이너를 다시 생성해 적용합니다. 분석용 runner 포트는 외부에 공개하지 않습니다.

## 1Password 로그인

로그인과 초기 비밀번호 설정은 서로 다른 폼을 사용합니다. 1Password에서 저장된 로그인을 선택하면 자동 입력·제출할 수 있도록 표준 로그인 폼을 제공합니다.

자동 입력만 되고 제출되지 않는다면 해당 로그인 항목의 자동 로그인 설정과 확장 프로그램의 **Autofill & save → Sign in automatically after autofill**을 확인하세요. 서비스가 임의로 비밀번호 입력 이벤트를 감지해 로그인하지는 않습니다.
