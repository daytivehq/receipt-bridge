FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY receipt_bridge ./receipt_bridge
COPY config.container.toml ./config.toml
RUN pip install -c requirements.lock . && useradd --uid 10001 --create-home bridge && mkdir /data /ai-home /runner-auth && chown bridge:bridge /data /ai-home /runner-auth

FROM base AS test
COPY tests ./tests
RUN pip install -c requirements.lock '.[test]'
USER bridge
ENV PYTEST_ADDOPTS="-p no:cacheprovider"
ENTRYPOINT ["python", "-m", "pytest"]

FROM node:22-bookworm-slim AS node-runtime

# Build dependencies in the image: a fresh checkout has no host node_modules.
FROM node-runtime AS ui-test
WORKDIR /workspace/tests/ui
COPY tests/ui/package.json tests/ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tests/ui ./
COPY receipt_bridge/static /workspace/receipt_bridge/static
CMD ["sh", "-c", "npm test && node --check /workspace/receipt_bridge/static/app.js && node --check /workspace/receipt_bridge/static/settings.js"]

# Published runner includes all supported CLIs; selection happens per request.
FROM base AS cli
USER root
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
ARG CODEX_VERSION=0.166.0
ARG CLAUDE_VERSION=2.1.318
COPY docker/agy-release.json docker/install_agy.py /tmp/
RUN npm install -g "@openai/codex@$CODEX_VERSION" "@anthropic-ai/claude-code@$CLAUDE_VERSION" \
    && python /tmp/install_agy.py \
    && test "$(agy --version)" = "1.5.0" \
    && rm -f /tmp/install_agy.py /tmp/agy-release.json
USER bridge
ENTRYPOINT ["python", "-m", "receipt_bridge.main", "ai-runner"]

FROM base AS runtime
USER bridge
ENTRYPOINT ["python", "-m", "receipt_bridge.main"]
CMD ["--config", "/app/config.toml", "run"]
