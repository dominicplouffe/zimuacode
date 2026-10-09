import { defineConfig } from '@playwright/test'
import path from 'node:path'

const PORT = 8765
const FAKE_GITHUB_PORT = 9001

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  // The fake GitHub is shared, stateful and reset before each test, so tests run one at a time.
  workers: 1,
  use: {
    baseURL: `http://localhost:${PORT}`,
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  // Runs against the production build served by the real server, with GitHub faked.
  webServer: [
    {
      command: `uv run uvicorn tests.fake_github:app --port ${FAKE_GITHUB_PORT}`,
      cwd: '../server',
      port: FAKE_GITHUB_PORT,
      reuseExistingServer: false,
    },
    {
      command: `rm -rf .e2e-data && uv run python -m tests.e2e_setup .e2e-data/git && uv run uvicorn app.main:app --port ${PORT}`,
      cwd: '../server',
      port: PORT,
      reuseExistingServer: false,
      env: {
        ZIMUA_DATABASE_URL: 'sqlite:///./.e2e-data/zimua.db',
        ZIMUA_GITHUB_API_URL: `http://localhost:${FAKE_GITHUB_PORT}`,
        ZIMUA_ALLOWED_GITHUB_LOGIN: 'octo',
        ZIMUA_PUBLIC_URL: `http://localhost:${PORT}`,
        ZIMUA_DEV_LOGIN: '1',
        ZIMUA_WEB_DIST: '../web/dist',
        ZIMUA_DATA_DIR: './.e2e-data',
        ZIMUA_GIT_URL_TEMPLATE: `file://${path.resolve('../server/.e2e-data/git')}/{owner}/{name}.git`,
        ZIMUA_CLAUDE_BIN: `python3 ${path.resolve('../server/tests/fake_agent.py')}`,
      },
    },
  ],
})
