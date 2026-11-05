# AI 연결

사진 설명과 지출 텍스트도 같은 AI를 사용합니다. 여러 지출은 공통 JSON 형식으로 나누어 검증하며, 항상 개별 확인 후 저장합니다.

0.2.0부터 분석 이미지에 Codex·Claude·Antigravity CLI가 모두 포함됩니다. 제공자·모델·시간 제한은 **웹에서 변경하고 저장**하면 다음 작업부터 적용됩니다. `.env`에 제공자를 다시 입력하거나 CLI를 따로 빌드하지 않습니다.

기본 Compose가 분석 서비스를 함께 시작하고, 통신용 토큰은 별도 볼륨에서 자동 생성·공유합니다. AI에는 가계부 키·Telegram 토큰·DB를 전달하지 않습니다.

## 웹에서 설정

1. 서비스 설정 → AI 분석에서 제공자와 모델 이름을 선택합니다.
2. CLI를 사용한다면 외부 AI 전송 허용을 켭니다.
3. 변경 사항 저장을 누릅니다.
4. CLI의 **연결·설치 확인**으로 실행 상태를 확인합니다. Antigravity는 조회된 모델 버튼으로 모델 이름을 입력한 뒤 다시 저장할 수 있습니다.

| 제공자 | 전송 데이터 | 최초 준비 |
| --- | --- | --- |
| Ollama | 보정 사진 | 별도 Ollama 서버에 이미지 입력을 지원하는 모델 설치 |
| Codex CLI | 보정 사진 | 아래 명령으로 계정 로그인 |
| Claude Code CLI | 보정 사진 | 웹에서 Claude API 키 저장. API 사용 요금 발생 가능 |
| Antigravity CLI | 로컬 OCR 텍스트 | 아래 명령으로 Google 로그인. 항상 확인 후 저장 |

CLI 분석 주소의 기본값은 `http://ai-runner:8090`입니다. 같은 Compose를 사용하면 바꾸지 않아도 됩니다. 다른 AI로 자동 우회 전송하지 않습니다.

## Ollama

모델은 서버의 CPU·메모리·GPU에 맞게 직접 준비합니다. 웹에서 설치한 모델 이름과 컨테이너가 접근할 수 있는 Ollama 주소를 입력하세요. 예: `http://서버IP:11434`.

컨테이너의 `127.0.0.1`은 호스트가 아닙니다. 주소 선택과 `host.docker.internal` 설정은 [Compose 안내](compose.md#연결-주소)를 참고하세요. Ollama 접근은 신뢰하는 장치로 제한합니다.

## 최초 CLI 인증

계정 로그인은 서비스가 대신 승인할 수 없습니다. 서버의 Compose 설치 폴더에서 한 번만 실행합니다. 이후 인증은 `ai-home` 볼륨에 보관되며, 제공자를 바꿀 때마다 다시 설치하지 않습니다.

### Antigravity

```bash
docker compose run --rm -e HOME=/ai-home -e SSH_CONNECTION="127.0.0.1 1 127.0.0.1 22" --entrypoint agy ai-runner
```

표시된 인증 주소를 본인 브라우저에서 열고 Google 로그인을 마칩니다. 표시된 인증 코드를 터미널에 입력한 뒤 CLI를 종료합니다. 이 명령의 SSH 환경값은 컨테이너에서 원격 로그인 안내를 표시하기 위한 것입니다.

모델 목록은 웹의 연결 확인 버튼 또는 다음 명령으로 조회합니다.

```bash
docker compose run --rm -T -e HOME=/ai-home --entrypoint agy ai-runner models
```

**모델 목록은 로그인 전에도 조회될 수 있습니다.** 목록 조회 성공이 로그인 완료를 뜻하지는 않습니다. 계정의 모델 접근 권한·만료 여부는 실제 분석 시 확인됩니다.

Codex·Claude는 사진과 함께 입력한 설명도 해당 AI에 전달합니다. 텍스트만 보낸 메시지는 이미지 없이 텍스트만 전달합니다.

Antigravity에는 원본 사진 대신 로컬 OCR 텍스트를 보냅니다. OCR 결과가 없으면 중단하며, 숫자를 확인한 뒤 저장해야 합니다. `/logout`은 저장한 인증을 삭제합니다.

### Codex

```bash
docker compose run --rm -e HOME=/ai-home -e CODEX_HOME=/ai-home/.codex --entrypoint codex ai-runner login --device-auth
```

표시된 주소·코드로 로그인합니다. 웹의 연결 확인은 저장된 인증의 존재를 검사하며, 실제 모델 사용 권한까지 보장하지 않습니다.

### Claude

웹에서 Claude를 선택하고 설정을 저장한 뒤, AI 분석 영역에서 **Claude API 키 → API 키 저장**을 누릅니다. 키는 분석 전용 볼륨에 저장하며 브리지 DB에는 저장하지 않습니다. 키 입력란은 저장 후 비웁니다.

이 서비스는 Claude의 `--bare` 모드를 사용하므로 API 키 방식입니다. 구독 OAuth 로그인은 사용하지 않습니다. 저장된 키의 실제 유효성은 분석 요청 시 확인됩니다.

## 연결이 안 될 때

- **분석 서비스 연결 실패:** `docker compose ps`와 `docker compose logs --tail=50 ai-runner`로 실행 상태를 확인합니다.
- **통신 인증 불일치:** 두 서비스가 같은 `runner-auth` 볼륨을 공유하는지 확인합니다. 기존 `AI_RUNNER_TOKEN`을 사용한다면 두 서비스에 같은 값을 지정해야 합니다.
- **이전 이미지 안내:** 영수증·분석 이미지를 함께 업데이트합니다. 새 구성은 0.2.0 이상 두 이미지가 필요합니다.
- **로그인·모델 오류:** 계정 로그인을 다시 확인하고 해당 계정에 허용된 모델을 선택합니다.

분석 서비스의 8090 포트와 Docker 소켓은 외부에 공개하지 않습니다.

공식 문서: [Antigravity 인증](https://antigravity.google/docs/install/), [Antigravity headless](https://antigravity.google/docs/cli/headless/), [Codex CLI](https://developers.openai.com/codex/cli/reference/), [Claude headless](https://code.claude.com/docs/en/headless), [Ollama](https://docs.ollama.com/capabilities/vision).
