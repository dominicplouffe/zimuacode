# Zimua Code

A web IDE, similar to VS Code, for working with Claude Code and Codex on your GitHub repos. It runs in the browser or as an Electron app, both talking to one server you host.

**Status:** Phases 1–3 of 5 (see [Roadmap](#roadmap)). You can sign in with GitHub, browse any repo and branch, edit and commit files, review and merge pull requests, read CI logs, change settings and themes, and run Claude Code tasks on your server that keep going with your laptop off.

## How it fits together

```
browser / Electron ──► server (FastAPI) ──► GitHub API
                          │
                          └─► one Docker container per agent task, running the
                              official `claude` / `codex` CLIs with your subscription
```

- `server/`: Python 3.12, FastAPI, SQLite. Handles GitHub OAuth (single user), the GitHub API, settings and themes. In production it also serves the built web app.
- `web/`: React, Vite, TypeScript, Monaco. The API types are generated from the server's OpenAPI schema (`npm run gen:api`).
- `desktop/`: Electron shell that loads the web app from your server.
- `shared/`: `settings.schema.json` (defaults and validation) and color themes in VS Code format.
- `deploy/`: Docker Compose and Caddy for a single VM.

## Development

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/) and Node 22.

1. Create a GitHub OAuth app at https://github.com/settings/developers.
   - Homepage URL: `http://localhost:5173`
   - Authorization callback URL: `http://localhost:5173/api/auth/callback`
2. Start the server:
   ```sh
   cd server
   cat > .env <<EOF
   ZIMUA_GITHUB_CLIENT_ID=...
   ZIMUA_GITHUB_CLIENT_SECRET=...
   ZIMUA_ALLOWED_GITHUB_LOGIN=your-github-username
   EOF
   uv sync
   uv run uvicorn app.main:app --reload
   ```
3. Start the web app (Vite proxies `/api` to the server):
   ```sh
   cd web
   npm install
   npm run dev
   ```
4. Open http://localhost:5173.

### Checks

```sh
cd server && uv run ruff check . && uv run mypy app && uv run pytest
cd web && npm run typecheck && npm run lint && npm test
cd web && npx vite build && npm run e2e   # Playwright against a fake GitHub
```

To run all of these in GitHub Actions, copy `deploy/github-ci.yml` to `.github/workflows/ci.yml`.

## Deploying to a VM

1. Point a domain at the VM and install Docker.
2. Create a GitHub OAuth app with the callback `https://<domain>/api/auth/callback`.
3. Configure and start it:
   ```sh
   cd deploy
   cp .env.example .env    # then fill it in
   sudo mkdir -p /srv/zimua && sudo chown 1000:1000 /srv/zimua
   docker compose up -d --build
   ```
   This also builds `zimua-runner:latest`, the image agent tasks run in.

## Desktop app

```sh
cd desktop
npm install
ZIMUA_SERVER_URL=https://ide.example.com npm start
```

You can also save `{"serverUrl": "https://ide.example.com"}` to `config.json` in the app's user-data folder instead of setting the variable.

## Agent tasks

Open **Agent Tasks** in the activity bar (or "Agent: New Task…" in the command palette), describe the work and start. Each task:

- clones the repo into its own workspace on the server, on a new branch `zimua/<summary>-<id>`;
- runs the agent CLI there, streaming its transcript (messages, tool calls, results, cost) to the IDE live;
- takes follow-ups (queued if the agent is still working) and can be interrupted;
- shows its changed files with live diffs, and publishes them as a pull request (or pushes to its existing one).

Turns run detached from the server and write to a log on disk, so a task keeps going when you close the browser, and the server picks it back up after a restart.

**Signing in an agent:** open "Agent: Accounts". For Claude Code, run `claude setup-token` on your computer and paste the token; it uses your Pro/Max subscription. An Anthropic API key also works. Credentials are stored encrypted on the server and only passed to the CLI.

**Sandboxes** (`ZIMUA_SANDBOX`):
- `docker` (the Compose default): one container per task from `runner-image/`, as a non-root user. The agent runs with permission prompts off, because the container is the boundary. Your GitHub token never enters the container; the server does the git clone and push itself.
- `local` (the development default): the agent runs as a plain process on the server machine with permission prompts off. Use it only on a machine dedicated to this.

## Settings

Open them with **⌘,** (Ctrl+, on Windows and Linux), the gear icon, or "Preferences: Open Settings (JSON)". The file is validated against `shared/settings.schema.json`, and any key you leave out uses its default.

| Key | Default |
| --- | --- |
| `workbench.theme` | `"dark"` (also `light`, `high-contrast`) |
| `editor.fontSize` | `14` |
| `editor.fontFamily` | system monospace |
| `editor.tabSize` | `4` |
| `editor.wordWrap` | `"off"` |
| `editor.minimap` | `false` |
| `ai.defaultProvider` | `"claude-code"` |
| `ai.defaultModel` | `""` (the provider's default) |
| `notifications.enabled` | `true` |

To add a theme, drop a VS Code color theme JSON into `shared/themes/`.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| ⌘P | Go to file |
| ⌘⇧P | Command palette |
| ⌘B | Toggle sidebar |
| ⌘, | Settings |
| ⌘S | Save (settings editor) |

## Roadmap

1. **Skeleton** ✅: GitHub sign-in, repo and branch browsing, editor, quick open, command palette, settings, themes, Electron shell, deploy files.
2. **Git** ✅: branches (switch, create, delete), editing with a per-branch working copy, atomic commits (to the branch or a new one), PR list and PR view (description, checks, files and diffs, conversation, comments, merge), CI logs, PR and CI status in the status bar.
3. **Agent runner and Claude Code** ✅: per-task workspaces and containers running `claude -p --output-format stream-json` with your subscription token, a live transcript, queued follow-ups, interrupt, changed files with live diffs, publish to a PR, recovery after server restarts.
4. **Codex and cloud dispatch**: `codex exec --json` in the runner. Hand-off to Claude Code on the web (`claude --cloud`) and Codex Cloud, with reduced visibility because neither has a public API.
5. **Extras**: push notifications, preview URLs for dev servers, a terminal, per-repo secrets and setup scripts, a usage view, and "Fix CI".

> Running the official CLIs with your own subscription is meant for your personal use. Anthropic doesn't allow third-party products to offer claude.ai login, so don't run this as a service for other people.
