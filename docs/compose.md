# Compose 설정

## 파일 선택

| 파일 | 용도 |
| --- | --- |
| `compose.minimal.yaml` | 기본 이미지로 간단하게 운영. README에 나온 구성과 같습니다. |
| `compose.yaml` | 설정 파일·환경변수·추가 보호 옵션·CLI 분석을 사용하는 구성 |
| `compose.dev.yaml` | 운영과 데이터가 분리된 개발 환경 |
| `compose.test.yaml` | 자동 테스트 |
| `compose.build.yaml` | `compose.yaml`과 함께 사용해 소스에서 이미지 빌드 |

처음 설치한다면 README의 구성을 `compose.yaml`로 저장하세요. 저장소를 클론했다면 최소 구성은 `docker compose -f compose.minimal.yaml up -d`로 실행합니다. 이후 조회·중지·업데이트 명령에도 같은 `-f compose.minimal.yaml`을 붙이세요.

저장소의 기본 `compose.yaml`을 사용할 때는 먼저 `.env.example`을 `.env`로, `config.example.toml`을 `config.toml`로 복사합니다. 이 구성의 기본 접속 주소는 `http://127.0.0.1:8092/`입니다. 기존 설정 파일은 덮어쓰지 마세요.

가계부·Telegram·AI 연결 값은 웹에서 저장합니다. Docker의 포트·저장 공간·메모리 제한은 Compose에서 설정합니다.

## 기본 항목

| 항목 | 의미 |
| --- | --- |
| `name` | 프로젝트 이름. 데이터 볼륨 이름에도 영향을 줍니다. |
| `services` | 실행할 서비스 목록 |
| `container_name` | 컨테이너 이름을 고정. 생략하면 Docker가 정합니다. |
| `image` | 내려받아 실행할 이미지 |
| `restart: unless-stopped` | 장애나 서버 재시작 후 다시 실행. 직접 중지하면 중지 상태를 유지합니다. |
| `ports` | `서버포트:컨테이너포트`. `8892:8092`는 서버의 8892로 앱에 접속하도록 연결합니다. |
| 서비스의 `volumes` | 데이터·설정 파일을 컨테이너에 연결. `/data`에는 DB·설정·원본을 보관합니다. |
| 최상위 `volumes` | 사용할 데이터 볼륨 선언. 기본적으로 Docker가 생성합니다. |
| 볼륨의 `name`, `external: true` | 특정 이름의 기존 볼륨 사용. `external`이면 볼륨이 없을 때 시작하지 않습니다. |
| `mem_limit` | 메모리 사용 상한. 기본은 2GB이며, 초과하면 프로세스가 종료될 수 있습니다. |

포트에 IP를 지정하지 않으면 서버에서 접근 가능한 네트워크에 화면이 열립니다. 서버 자신에서만 접속하려면 `127.0.0.1:8892:8092`로 제한하세요.

## 선택 항목

| 항목 | 의미·필요한 경우 |
| --- | --- |
| `entrypoint`, `command` | 이미지의 시작 프로그램·실행 인수 변경. 일반 실행에서는 기본값을 사용합니다. |
| `environment`, `env_file` | 환경변수를 직접 지정하거나 파일에서 읽기. 별도 CLI 분석 설정 등에 사용합니다. |
| `init` | 자식 프로세스 정리와 종료 신호 전달 보조 |
| `networks` | 다른 서비스와 연결할 Docker 네트워크 지정. 생략해도 기본 네트워크는 생성됩니다. |
| `extra_hosts` | 주소 별칭 추가. Linux에서 `host.docker.internal`을 사용할 때 필요합니다. |
| `read_only` | 컨테이너 기본 파일 시스템 쓰기 금지. 데이터 볼륨은 별도입니다. |
| `tmpfs` | 임시 경로를 메모리 기반 저장 공간으로 제공. 영구 보관하지 않습니다. |
| `cap_drop` | Linux 추가 권한 제거 |
| `security_opt` | 권한 상승 제한 등 보안 옵션 |
| `pids_limit` | 프로세스·스레드 수 제한 |
| `stop_grace_period` | 강제 종료하기 전에 기다릴 시간 |
| `build.context`, `build.target`, `build.args` | 소스 폴더, Dockerfile 빌드 단계, 빌드에 전달할 값 |
| `pull_policy: build` | 로컬 소스에서 이미지를 빌드하도록 지정 |
| `profiles` | 명시했을 때만 추가 서비스 실행. CLI 분석 컨테이너에 사용합니다. |
| `${변수:-기본값}` | 환경변수가 없거나 비어 있으면 기본값 사용 |

`read_only`·`cap_drop`·`security_opt`는 추가 보호 옵션입니다. 최소 구성은 단순하게 유지하며, 더 엄격한 설정은 저장소의 기본 `compose.yaml`을 참고하세요. 이미지는 일반 사용자 권한으로 실행됩니다.

## 연결 주소

- **도메인:** `https://ledger.example.com/api/v1`. 컨테이너에서도 접속 가능한 주소여야 합니다.
- **서버 IP:** `http://서버IP:공개포트/api/v1`. 가계부가 호스트에 공개한 포트를 사용합니다.
- **Docker 서비스 이름:** `http://duet-ledger:8080/api/v1`. 두 서비스가 같은 Docker 네트워크에 있어야 하며, 컨테이너 내부 포트를 사용합니다. 다른 Compose 프로젝트의 이름은 자동으로 인식하지 않습니다.
- **호스트의 서비스:** Linux에서 `host.docker.internal`을 사용하려면 다음을 서비스 아래에 추가합니다.

  ```yaml
  extra_hosts:
    - host.docker.internal:host-gateway
  ```

Ollama도 같은 기준으로 주소를 정합니다. 컨테이너 안의 `localhost`나 `127.0.0.1`은 호스트가 아닌 해당 컨테이너입니다.

## 기존 설치 유지

Compose 파일 이름·설치 폴더·프로젝트 이름을 바꾸면 새 볼륨이 선택될 수 있습니다. 기존 컨테이너의 저장 공간 이름은 다음으로 확인합니다.

```bash
docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' 기존컨테이너이름
```

Docker 볼륨을 사용했다면 새 파일의 최상위 선언에 실제 이름을 지정합니다.

```yaml
volumes:
  receipt-data:
    external: true
    name: 실제_기존_볼륨_이름
```

호스트 폴더를 연결했던 설치는 기존 폴더 연결을 그대로 유지하세요. **같은 데이터를 사용하는 기존 컨테이너를 먼저 중지하고 새 컨테이너를 시작합니다. 볼륨은 삭제하지 마세요.** 별도 네트워크를 제거했다면 웹의 가계부·AI 주소도 도메인이나 서버 IP로 변경해야 합니다.
