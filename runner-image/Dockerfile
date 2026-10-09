# The image each agent task runs in: both agent CLIs plus common Python and JS tooling.
# The server starts one container per task and runs turns in it with `docker exec`.
FROM node:22-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ca-certificates curl ripgrep jq less procps \
        python3 python3-venv python3-pip build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /usr/local/bin/

# Pin versions here if you want reproducible agents; unpinned gets the latest on rebuild.
RUN npm install -g @anthropic-ai/claude-code @openai/codex && npm cache clean --force

# The node image's "node" user is uid 1000, the same uid the server runs as, so files in
# the shared workspace have one owner. Agents never run as root.
USER node
WORKDIR /workspace/repo
CMD ["sleep", "infinity"]
