import { expect, test, type Page } from '@playwright/test'

const FAKE_GITHUB = 'http://localhost:9001'

test.beforeEach(async ({ page, request }) => {
  await request.post(`${FAKE_GITHUB}/__reset`)
  expect((await page.request.post('/api/auth/dev-login', { data: { token: 'fake' } })).ok()).toBeTruthy()
})

async function openShop(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Open Repository' }).first().click()
  await page.getByRole('option', { name: /octo\/shop/ }).click()
  await expect(page.getByRole('tree', { name: 'Files' }).getByText('README.md')).toBeVisible()
}

async function command(page: Page, text: string) {
  await page.keyboard.press('Control+Shift+p')
  await page.getByPlaceholder('Type a command').fill(text)
  await page.keyboard.press('Enter')
}

async function startTask(page: Page, prompt: string) {
  await page.getByRole('button', { name: 'Agent Tasks' }).click()
  await page.getByRole('button', { name: 'New Task' }).first().click()
  await page.getByLabel('Task prompt').fill(prompt)
  await page.getByRole('button', { name: 'Start task' }).click()
  await expect(page.locator('.task-status')).toHaveText('Waiting for you')
}

test('repo env vars and setup script reach the agent', async ({ page }) => {
  await openShop(page)
  await command(page, 'repository settings')
  await page.getByLabel('Variable name').fill('GREETING')
  await page.getByLabel('Variable value').fill('hello-from-env')
  await page.getByRole('button', { name: 'Add' }).click()
  await expect(page.getByRole('list', { name: 'Variables' }).getByText('GREETING')).toBeVisible()
  await page.getByRole('textbox', { name: 'Setup script' }).fill('echo "setup says $GREETING"')
  await page.getByRole('button', { name: 'Save script' }).click()
  await expect(page.getByText('Saved.')).toBeVisible()

  await startTask(page, 'env GREETING')
  const transcript = page.locator('.transcript')
  await expect(transcript.getByText('GREETING=hello-from-env')).toBeVisible()
  await transcript.getByText(/CLI output/).first().click()
  await expect(transcript.getByText('setup says hello-from-env')).toBeVisible()

  // Clean up so other tests start without a setup script.
  await command(page, 'repository settings')
  await page.getByRole('textbox', { name: 'Setup script' }).fill('')
  await page.getByRole('button', { name: 'Save script' }).click()
  await page.getByRole('list', { name: 'Variables' }).getByRole('button', { name: 'Remove' }).click()
})

test('terminal and preview of a dev server in the workspace', async ({ page, context }) => {
  await openShop(page)
  await startTask(page, 'Write a page')
  await page.getByRole('button', { name: 'Terminal' }).click()
  const terminal = page.getByTestId('terminal-view')
  await expect(terminal.locator('.xterm-rows')).toBeVisible()
  await terminal.click()
  await page.keyboard.type('echo answer=$((6*7))\n')
  await expect(terminal.locator('.xterm-rows')).toContainText('answer=42')

  // A short-lived static server stands in for `npm run dev`.
  const port = 4600 + Math.floor(Math.random() * 300)
  await page.keyboard.type(`timeout 60 python3 -m http.server ${port} --bind 0.0.0.0\n`)
  await expect(terminal.locator('.xterm-rows')).toContainText('Serving HTTP')

  await page.getByLabel('Preview port').fill(String(port))
  const [preview] = await Promise.all([context.waitForEvent('page'), page.getByRole('button', { name: 'Open preview' }).click()])
  // Opens blank first (popup blockers), then lands on the preview origin.
  await preview.waitForURL(/^http:\/\/127\.0\.0\.1:8765\//)
  await expect(preview.getByRole('link', { name: 'AGENT.md' })).toBeVisible()
  await preview.getByRole('link', { name: 'AGENT.md' }).click()
  await expect(preview.locator('body')).toContainText('Write a page')

  // The shell keeps running when the panel is hidden and shown again.
  await page.getByRole('button', { name: 'Hide terminal' }).click()
  await page.getByRole('button', { name: 'Terminal' }).click()
  await expect(page.getByTestId('terminal-view').locator('.xterm-rows')).toContainText('answer=42')
  await page.getByRole('button', { name: 'Kill' }).click()
})

test('fix a failing check with an agent on the PR branch', async ({ page }) => {
  await openShop(page)
  await page.getByRole('button', { name: 'Pull Requests' }).click()
  await page.getByRole('list', { name: 'Pull requests' }).getByText('Legacy cleanup').click()
  await page.getByRole('button', { name: 'Fix with agent' }).click()

  await expect(page.getByLabel('Task prompt')).toHaveValue(/The CI check "test" is failing on pull request #1/)
  await expect(page.getByLabel('Task prompt')).toHaveValue(/ERROR: Process completed with exit code 1\./)
  await expect(page.getByLabel('Base branch')).toHaveValue('feature/legacy')
  await expect(page.getByText('so publishing pushes to PR #1')).toBeVisible()
  await page.getByRole('button', { name: 'Start task' }).click()
  await expect(page.locator('.task-status')).toHaveText('Waiting for you')
  await expect(page.locator('.task-header')).toContainText('feature/legacy')
  await expect(page.getByRole('button', { name: 'Push changes to PR' })).toBeVisible()
})

test('usage and notification links', async ({ page }) => {
  await openShop(page)
  await startTask(page, 'Count my tokens')
  await command(page, 'agent: usage')
  await expect(page.getByRole('heading', { name: 'Agent usage' })).toBeVisible()
  await expect(page.getByRole('row', { name: /claude-code/ })).toBeVisible()

  // Notification clicks land on #pr=… and open the PR.
  await page.goto('/#pr=octo/shop/1')
  await expect(page.getByRole('heading', { name: /Legacy cleanup #1/ })).toBeVisible()
})
