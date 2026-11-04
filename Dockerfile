FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY receipt_bridge ./receipt_bridge
COPY config.container.toml ./config.toml
RUN pip install -c requirements.lock . && useradd --uid 10001 --create-home bridge && mkdir /data && chown bridge:bridge /data

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

# Optional CLI runner: explicit versions, selected provider only, no ledger/bot secrets.
FROM base AS cli
USER root
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
ARG CLI_PROVIDER=codex
ARG CODEX_VERSION
ARG CLAUDE_VERSION
ARG AGY_VERSION
RUN if [ "$CLI_PROVIDER" = codex ]; then \
      test -n "$CODEX_VERSION" && npm install -g "@openai/codex@$CODEX_VERSION"; \
    elif [ "$CLI_PROVIDER" = claude ]; then \
      test -n "$CLAUDE_VERSION" && npm install -g "@anthropic-ai/claude-code@$CLAUDE_VERSION"; \
    elif [ "$CLI_PROVIDER" = agy ]; then \
      test -n "$AGY_VERSION" && apt-get update && apt-get install -y --no-install-recommends curl \
      && curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/install-agy.sh \
      && bash /tmp/install-agy.sh --dir /usr/local/bin \
      && test "$(agy --version)" = "$AGY_VERSION" \
      && rm -f /tmp/install-agy.sh && rm -rf /var/lib/apt/lists/*; \
    else exit 1; fi
USER bridge
ENTRYPOINT ["python", "-m", "receipt_bridge.main", "ai-runner"]

FROM base AS runtime
USER bridge
ENTRYPOINT ["python", "-m", "receipt_bridge.main"]
CMD ["--config", "/app/config.toml", "run"]
