# Builds the web app, then serves it from the API server.
FROM node:22-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npx tsc --noEmit && npx vite build

FROM python:3.12-slim
# git: the server clones, diffs and pushes task workspaces. docker CLI: it starts a
# container per task (through the host's Docker socket).
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY server/ ./
RUN uv sync --frozen --no-dev
COPY shared/ /app/shared/
COPY --from=web /src/web/dist /app/web/dist

ENV ZIMUA_SHARED_DIR=/app/shared \
    ZIMUA_WEB_DIST=/app/web/dist \
    ZIMUA_COOKIE_SECURE=true \
    UV_CACHE_DIR=/tmp/uv-cache
# Runs as uid 1000, like the agents in their containers.
RUN chown -R 1000:1000 /app
USER 1000:1000
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
