# 이미지 발행

저장소 관리자를 위한 안내입니다. 일반 사용자는 README의 설치·업데이트 방법만 따르면 됩니다.

## 릴리즈

1. `receipt_bridge/__init__.py`의 버전을 올리고 변경 사항을 `main`에 커밋·푸시합니다. 실제 설정·접속 키·DB가 포함되지 않았는지 확인합니다.
2. GitHub의 **Releases → Draft a new release**에서 최신 커밋에 `v버전` 태그를 새로 만듭니다. 예: 프로그램 버전 `0.2.0` → 태그 `v0.2.0`.
3. 릴리즈 내용을 작성하고 정식 릴리즈로 발행합니다.
4. **Actions → Docker image**에서 테스트와 이미지 발행이 모두 성공했는지 확인합니다.
5. 처음 발행할 때는 저장소 소유자의 **Packages → receipt-bridge → Package settings**에서 `receipt-bridge`와 `receipt-bridge-ai-runner` 패키지를 모두 **Public**으로 설정합니다.

워크플로 파일은 `.github/workflows/docker.yml`입니다. `main` 푸시와 PR에서는 테스트만 실행하고, 정식 릴리즈를 게시하면 테스트 후 GHCR에 영수증 서비스와 분석 서비스의 AMD64·ARM64 이미지를 발행합니다. 태그와 프로그램 버전이 다르면 발행하지 않습니다.

인증에는 GitHub의 `GITHUB_TOKEN`을 사용합니다. 별도 개인 토큰을 코드에 넣지 않습니다. 조직에서 Actions나 패키지 생성을 제한했다면 관리자가 권한을 허용해야 합니다.

**이미 발행한 버전은 덮어쓰지 않고 새 버전으로 발행합니다.** 두 이미지의 버전 태그를 모두 발행한 뒤 `latest`를 갱신하며, 홈서버의 실행 중인 서비스는 자동 갱신하지 않습니다.

## 결과 확인

```bash
docker pull ghcr.io/daytivehq/receipt-bridge:latest
docker pull ghcr.io/daytivehq/receipt-bridge-ai-runner:latest
docker buildx imagetools inspect ghcr.io/daytivehq/receipt-bridge:latest
docker run --rm --entrypoint python ghcr.io/daytivehq/receipt-bridge:latest -c 'from receipt_bridge import __version__; print(__version__)'
```

CLI 버전은 Dockerfile에서 관리합니다. Antigravity는 `docker/agy-release.json`의 공식 배포 URL과 SHA-512로 검증한 뒤 설치합니다. CLI를 갱신할 때는 두 아키텍처의 배포 정보와 실행 호환성을 확인하세요.

0.1.x에는 새 분석 이미지가 없습니다. 0.2.0 릴리즈의 두 이미지 발행이 완료된 뒤 새 Compose를 사용하세요.
