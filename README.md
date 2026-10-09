# Zimua Code

A web IDE, similar to VS Code, for working with Claude Code and Codex on your GitHub repos. It runs in the browser or as an Electron app, both talking to one server you host.

**Status:** Phase 1 of 5 (see [Roadmap](#roadmap)). You can sign in with GitHub, browse any repo and branch, open files in the editor, and change settings and themes. Agent tasks start in Phase 3.

## How it fits together

```
browser / Electron ──► server (FastAPI) ──► GitHub API
                          │
                          └─► (Phase 3+) one Docker container per agent task,
                              running the official `claude` / `codex` CLIs
                              logged in with your subscriptions
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
   docker compose up -d --build
   ```

## Desktop app

```sh
cd desktop
npm install
ZIMUA_SERVER_URL=https://ide.example.com npm start
```

You can also save `{"serverUrl": "https://ide.example.com"}` to `config.json` in the app's user-data folder instead of setting the variable.

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
| `files.autoSave` | `"off"` |
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
2. **Git**: branches, PR list/detail/diff, CI checks and logs, create and merge PRs, editing and committing to a branch.
3. **Agent runner and Claude Code**: per-task containers running `claude -p --output-format stream-json` with your subscription login, a live task panel, follow-ups and interrupt, a live file view, diff review, then a PR.
4. **Codex and cloud dispatch**: `codex exec --json` in the runner. Hand-off to Claude Code on the web (`claude --cloud`) and Codex Cloud, with reduced visibility because neither has a public API.
5. **Extras**: push notifications, preview URLs for dev servers, a terminal, per-repo secrets and setup scripts, a usage view, and "Fix CI".

> Running the official CLIs with your own subscription is meant for your personal use. Anthropic doesn't allow third-party products to offer claude.ai login, so don't run this as a service for other people.
