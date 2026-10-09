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

async function startTask(page: Page, prompt: string) {
  await page.getByRole('button', { name: 'Agent Tasks' }).click()
  await page.getByRole('button', { name: 'New Task' }).first().click()
  await page.getByLabel('Task prompt').fill(prompt)
  await page.getByRole('button', { name: 'Start task' }).click()
}

test('sign in an agent account', async ({ page }) => {
  await openShop(page)
  await page.keyboard.press('Control+Shift+p')
  await page.getByPlaceholder('Type a command').fill('accounts')
  await page.keyboard.press('Enter')
  const claude = page.getByRole('region', { name: 'Claude Code' })
  await expect(claude.getByText('Not signed in')).toBeVisible()
  await claude.getByLabel('Claude Code credential').fill('sk-ant-oat-test')
  await claude.getByRole('button', { name: 'Save' }).click()
  await expect(claude.getByText('Signed in', { exact: true })).toBeVisible()
})

test('run a task: live transcript, changes, follow-up, publish a PR', async ({ page }) => {
  await openShop(page)
  await startTask(page, 'Add release notes')

  const transcript = page.locator('.transcript')
  await expect(transcript.getByText('Started: Add release notes')).toBeVisible()
  await expect(transcript.getByText('Write: AGENT.md')).toBeVisible()
  await expect(page.locator('.task-status')).toHaveText('Waiting for you')
  await expect(page.locator('.task-header')).toContainText('170 tokens · $0.01')

  // Changes in the workspace, with a live diff.
  const changes = page.getByRole('list', { name: 'Task changes' })
  await expect(changes.getByText('AGENT.md')).toBeVisible()
  await changes.getByText('AGENT.md').click()
  await expect(page.locator('.monaco-diff-editor').getByText('Add release notes')).toBeVisible()

  // A follow-up resumes the conversation.
  await page.getByRole('tab', { name: /Add release notes/ }).click()
  await page.getByLabel('Message the agent').fill('Also mention the fix')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(transcript.getByText('Resumed: Also mention the fix')).toBeVisible()
  await expect(page.locator('.task-status')).toHaveText('Waiting for you')

  // The task list shows it.
  await expect(page.getByRole('list', { name: 'Tasks' }).getByText('Add release notes').first()).toBeVisible()

  await page.getByLabel('Pull request title').fill('Release notes')
  await page.getByRole('button', { name: 'Create pull request' }).click()
  await expect(page.getByRole('heading', { name: /Release notes #2/ })).toBeVisible()
  await page.getByRole('tab', { name: /Add release notes/ }).click()
  await expect(page.getByText('Opened pull request #2')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Push changes to PR' })).toBeVisible()
})

test('queue a follow-up while working, then interrupt', async ({ page }) => {
  await openShop(page)
  await startTask(page, 'sleep 3')
  await expect(page.locator('.task-status')).toHaveText('Working')
  await page.getByLabel('Message the agent').fill('sleep 30')
  await page.getByRole('button', { name: 'Queue' }).click()
  await expect(page.getByText('Queued until the agent finishes')).toBeVisible()

  // The queued message starts on its own after the first turn.
  await expect(page.locator('.transcript').getByText('Resumed: sleep 30')).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: 'Interrupt' }).click()
  await expect(page.locator('.task-status')).toHaveText('Interrupted')
})

test('transcript survives a reload and the task can be archived', async ({ page }) => {
  await openShop(page)
  await startTask(page, 'Write the changelog')
  await expect(page.locator('.task-status')).toHaveText('Waiting for you')
  await page.reload()

  await page.getByRole('button', { name: 'Agent Tasks' }).click()
  await page.getByRole('list', { name: 'Tasks' }).getByText('Write the changelog').click()
  await expect(page.locator('.transcript').getByText('Started: Write the changelog')).toBeVisible()

  page.once('dialog', (d) => d.accept())
  await page.getByRole('button', { name: 'Archive task' }).click()
  await expect(page.locator('.task-status')).toHaveText('Archived')
  await expect(page.getByRole('list', { name: 'Tasks' }).getByText('Write the changelog')).toHaveCount(0)
})
