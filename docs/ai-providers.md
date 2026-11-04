# AI 연결

| 제공자 | 전달 데이터 | 준비 사항 |
| --- | --- | --- |
| Ollama | 보정 사진 | 이미지 입력·JSON 스키마 출력을 지원하는 모델 |
| Codex CLI | 보정 사진 | 전용 runner 설치와 Codex 인증 |
| Claude Code CLI | 보정 사진 | 전용 runner와 Anthropic API 키. 구독 OAuth는 지원하지 않음 |
| Antigravity CLI (`agy`) | 로컬 OCR 텍스트 | 전용 runner와 Google 로그인. 결과는 항상 확인 후 저장 |

서비스 설정에서 제공자와 모델을 선택합니다. CLI 제공자에는 **외부 AI 전송 허용**이 필요합니다. 가계부 키·Telegram 토큰은 AI에 전달하지 않습니다.

## Ollama

Ollama에 사용할 모델을 설치한 뒤 서비스 설정에 다음을 입력하세요.

- 제공자: Ollama
- 모델: 설치한 이미지 분석 모델 이름
- Ollama 주소: 호스트에 설치했다면 `http://host.docker.internal:11434`

Ollama가 컨테이너에서 접근 가능한 주소로 수신하고 있는지 확인하세요. Ollama 접근은 신뢰하는 장치로 제한합니다. 모델 크기는 홈서버의 CPU·메모리·GPU에 맞게 선택합니다.

## CLI 공통 준비

CLI는 가계부·원본·DB와 분리된 `ai-runner` 컨테이너에서 실행합니다. `secrets/ai-home`에는 AI 인증만 넣으며 개인 홈 전체를 연결하지 않습니다.

`.env`에 사용할 `AI_PROVIDER`와 해당 CLI 설치 버전을 지정합니다. 예: Antigravity라면 `AI_PROVIDER=agy`, `AGY_VERSION=사용할버전`입니다. 모델 이름은 웹 화면에서 설정합니다.

runner 전용 토큰을 생성해 `.env`의 `AI_RUNNER_TOKEN`에 저장합니다. 가계부 키나 봇 토큰을 재사용하지 마세요.

```bash
docker compose run --rm --no-deps --entrypoint python receipt-bridge -c 'import secrets; print(secrets.token_urlsafe(48))'
mkdir -p secrets/ai-home
sudo chown -R 10001:10001 secrets/ai-home
sudo chmod -R go-rwx secrets/ai-home
docker compose --profile cli build ai-runner
```

토큰은 브리지와 runner의 통신 인증에만 사용합니다. 변경하면 두 컨테이너를 다시 시작합니다. runner의 8090 포트는 외부에 공개하지 않습니다.

### Codex CLI

`.env`에 `AI_PROVIDER=codex`, `CODEX_VERSION`을 지정합니다. 전용 컨테이너에서 파일로 저장되는 인증을 준비하세요.

```bash
docker compose --profile cli run --rm -e HOME=/ai-home -e CODEX_HOME=/ai-home/.codex --entrypoint codex ai-runner login --device-auth
```

CLI는 읽기 전용 샌드박스에서 실행하며 명령 실행·웹 검색을 비활성화합니다. 선택한 모델의 이미지 입력 지원과 계정 접근 권한을 확인하세요.

### Claude Code CLI

`.env`에 `AI_PROVIDER=claude`, `CLAUDE_VERSION`을 지정합니다. `secrets/ai-home/anthropic-api-key`에 Anthropic API 키 한 줄을 넣고 컨테이너 UID `10001`만 읽도록 권한을 제한하세요.

이 연결은 `--bare` 모드이며 **API 과금 방식**입니다. 구독 로그인은 재사용하지 않습니다.

### Antigravity CLI

`.env`에 `AI_PROVIDER=agy`, `AGY_VERSION`을 지정합니다. 설치기는 배포 중인 버전을 내려받으며 지정 버전과 일치하지 않으면 빌드를 중단합니다.

```bash
docker compose --profile cli run --rm -e HOME=/ai-home -e SSH_CONNECTION -e SSH_CLIENT -e SSH_TTY --entrypoint agy ai-runner
```

대화형 화면에서 직접 로그인하고 종료합니다. `/logout`을 실행하면 저장된 인증이 지워집니다. SSH에서 표시된 로그인 URL과 코드는 본인이 직접 처리하세요.

```bash
docker compose --profile cli run --rm -T -e HOME=/ai-home --entrypoint agy ai-runner models
```

출력된 모델 ID를 웹 화면에 입력합니다. 모델 제공 여부는 계정에 따라 다릅니다. 직접 이미지 입력은 사용하지 않으며 OCR 결과가 없으면 중단합니다. 전용 폴더의 권한 설정 파일은 서비스가 관리하므로 개인 플러그인·MCP 설정을 추가하지 마세요.

## 실행

앞의 준비 단계에서 ai-runner를 빌드하고 인증한 뒤 실행합니다. 주 서비스는 GHCR의 `latest` 이미지를 사용하고 ai-runner만 로컬에서 빌드합니다.

```bash
docker compose pull receipt-bridge
docker compose --profile cli up -d --no-build receipt-bridge ai-runner
```

웹 설정에서 CLI 제공자·모델, 분석 주소 `http://ai-runner:8090`, 외부 전송 허용을 설정합니다. runner에 설치된 제공자와 웹 설정의 제공자가 같아야 합니다.

공식 문서: [Ollama](https://docs.ollama.com/capabilities/vision), [Codex](https://developers.openai.com/codex/noninteractive/), [Claude Code](https://code.claude.com/docs/en/headless), [Antigravity](https://antigravity.google/docs/cli/headless/).
