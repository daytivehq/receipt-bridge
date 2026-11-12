# 작업 지침

- 질문에 직접 필요한 내용만 쉬운 한국어로 답합니다.
- 데이터 삭제 등 중요한 위험은 짧고 명확하게 알립니다.
- 자세한 설명을 요청한 경우에만 길게 답합니다.
- 개선 후 필요한 테스트를 통과하면 개발용 서비스에 바로 반영합니다.
  - 실행: `docker compose --env-file .env.dev -f compose.dev.yaml up -d --build`
  - 개발용 포트: `18089`
  - 반영 후 접속 상태와 실행 버전을 확인합니다.
- 운영 서비스 배포는 사용자가 별도로 지시했을 때 진행합니다.
- 기존 개발용 설정·인증·데이터 볼륨을 유지합니다.
- `/data/projects/receipt-bridge` 체크아웃은 개발 전용입니다. 로컬 `.env`의 `COMPOSE_FILE=compose.dev.yaml`로 기본 실행도 개발용을 선택합니다.
- 공개 배포 예시인 `compose.yaml`의 운영 이름을 개발 이름으로 바꾸지 않습니다. 이 체크아웃에서 운영용 Compose를 직접 실행하지 않습니다.
- 운영 프로젝트는 `/data/services/docker/stacks/receipt-bridge`에서 관리하며, 운영 포트는 `8892`입니다.
