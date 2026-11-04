# GHCR 이미지 발행

## 첫 발행

1. `.github/workflows/docker.yml`을 포함한 최신 코드를 GitHub의 `main` 브랜치에 업로드합니다. `compose.yaml`, `.env.example`, 이 안내도 함께 올립니다. `.env`와 실제 `config.toml`은 올리지 않습니다.
2. `receipt_bridge/__init__.py`의 버전이 `0.1.0`인지 확인합니다.
3. GitHub 저장소의 **Releases → Draft a new release**에서 **새 태그 `v0.1.0`을 main의 최신 커밋에 생성**합니다. 설정 파일 업로드 전에 만든 오래된 태그를 재사용하지 마세요.
4. 릴리즈 제목·본문을 입력하고 **Publish release**를 누릅니다. 정식 발행에서는 prerelease 옵션을 끕니다.
5. **Actions → Docker image**에서 Tests와 Publish to GHCR이 모두 성공했는지 확인합니다. 릴리즈 본문을 게시하는 것만으로 이미지가 즉시 준비되지는 않습니다.
6. 처음에는 조직의 **Packages → receipt-bridge → Package settings**에서 패키지 공개 여부를 확인하고 **Public**으로 설정합니다. 공개된 뒤에는 Docker 로그인이 필요하지 않습니다.

개인 액세스 토큰을 만들거나 코드에 넣지 않습니다. GitHub가 발급하는 `GITHUB_TOKEN`으로 발행합니다. 조직에서 Actions 또는 패키지 생성을 제한했다면 저장소 관리자가 해당 권한을 허용해야 합니다.

워크플로는 main 업로드·PR에서 테스트만, 정식 릴리즈 게시에서 테스트 후 발행을 실행합니다. 릴리즈 태그와 프로그램 버전이 다르면 발행하지 않습니다. 이미 발행한 버전을 덮어쓰지 말고 수정 버전의 새 태그를 발행하세요. `latest`는 마지막으로 성공한 정식 발행을 가리키므로 운영은 버전 태그로 고정하는 것을 권장합니다.

다음 릴리즈에서는 `receipt_bridge/__init__.py`의 버전을 올리고 README 및 Compose 기본 이미지·설정 예시의 버전도 맞춘 뒤 새 `v버전` 태그를 생성합니다.

## 발행 결과 확인

두 Actions 작업이 성공하고 패키지를 공개한 다음 실행합니다.

```bash
docker pull ghcr.io/daytivehq/receipt-bridge:0.1.0
docker buildx imagetools inspect ghcr.io/daytivehq/receipt-bridge:0.1.0
docker run --rm --entrypoint python ghcr.io/daytivehq/receipt-bridge:0.1.0 -c 'from receipt_bridge import __version__; print(__version__)'
```

워크플로는 AMD64와 ARM64 이미지를 빌드하고 버전 태그와 `latest`를 발행합니다. 실제 두 플랫폼 빌드 성공 여부는 Actions에서 확인합니다. 홈서버에 자동으로 접속하거나 서비스를 업데이트하지는 않습니다.

## 이미지로 설치·업데이트

최초 설치 시 저장소의 `.env.example`과 `config.example.toml`을 복사해 설정 파일을 준비합니다. 이미지가 발행된 뒤에는 소스 빌드 없이 실행할 수 있습니다.

```bash
docker compose pull receipt-bridge
docker compose up -d --no-build receipt-bridge
```

업데이트 전에는 데이터를 백업하고, `.env`의 `RECEIPT_BRIDGE_IMAGE`를 새 버전으로 바꾼 뒤 같은 명령을 실행합니다. 같은 프로젝트 폴더와 데이터 볼륨을 사용해야 기존 자료가 유지됩니다.

CLI 분석용 ai-runner는 이 GHCR 이미지에 포함하지 않습니다. CLI를 사용할 때는 기존 AI 연결 안내에 따라 별도로 빌드·로그인합니다. 로컬에서 주 서비스를 직접 빌드하려면 `docker compose up -d --build receipt-bridge`를 사용합니다.
