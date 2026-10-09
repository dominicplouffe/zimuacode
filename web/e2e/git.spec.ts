import { expect, test, type Page } from '@playwright/test'

const FAKE_GITHUB = 'http://localhost:9001'

test.beforeEach(async ({ page, request }) => {
  await request.post(`${FAKE_GITHUB}/__reset`)
  // Each test starts with an empty working copy.
  await page.addInitScript(() => {
    if (!sessionStorage.getItem('zimua.e2e')) {
      localStorage.clear()
      sessionStorage.setItem('zimua.e2e', '1')
    }
  })
  expect((await page.request.post('/api/auth/dev-login', { data: { token: 'fake' } })).ok()).toBeTruthy()
})

async function openShop(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Open Repository' }).first().click()
  await page.getByRole('option', { name: /octo\/shop/ }).click()
  await expect(page.getByRole('tree', { name: 'Files' }).getByText('README.md')).toBeVisible()
}

async function editFile(page: Page, folder: string, file: string, text: string) {
  const tree = page.getByRole('tree', { name: 'Files' })
  await tree.getByText(folder, { exact: true }).click()
  await tree.getByText(file, { exact: true }).click()
  await page.locator('.editor-body .monaco-editor .view-lines').click()
  await page.keyboard.press('Control+End')
  await page.keyboard.insertText(text)
}

test('edit, review the diff, commit to a new branch and open a PR', async ({ page }) => {
  await openShop(page)
  await editFile(page, 'api', 'server.py', '# handled\n')

  const tree = page.getByRole('tree', { name: 'Files' })
  await expect(tree.getByRole('treeitem', { name: /server\.py M/ })).toBeVisible()
  await expect(page.getByRole('tab', { name: /server\.py.*modified/ })).toBeVisible()

  await page.getByRole('button', { name: 'Source Control' }).click()
  const changes = page.getByRole('list', { name: 'Changes' })
  await expect(changes.getByText('server.py')).toBeVisible()
  await changes.getByText('server.py').click()
  await expect(page.getByRole('tab', { name: /server\.py \(changes\)/ })).toBeVisible()
  await expect(page.locator('.monaco-diff-editor')).toBeVisible()

  await page.getByLabel('Commit message').fill('Handle requests')
  await page.getByLabel('Commit to a new branch').check()
  await page.getByLabel('New branch name').fill('feature/handler')
  await page.getByRole('button', { name: 'Commit to feature/handler' }).click()

  await expect(page.getByRole('button', { name: '⎇ feature/handler' })).toBeVisible()
  await expect(page.getByText('No uncommitted changes.')).toBeVisible()

  await page.getByRole('button', { name: 'Create Pull Request' }).click()
  await expect(page.getByLabel('Title')).toHaveValue('Handler')
  await page.getByLabel('Title').fill('Handle requests')
  await page.getByLabel('Description').fill('Adds a **handler** comment.')
  await page.locator('.pr-view').getByRole('button', { name: 'Create pull request' }).click()

  await expect(page.getByRole('heading', { name: /Handle requests #2/ })).toBeVisible()
  await expect(page.locator('.markdown strong', { hasText: 'handler' })).toBeVisible()
  await expect(page.getByRole('list', { name: 'Files changed' }).getByText('api/server.py')).toBeVisible()
  // The status bar now links the branch's PR.
  await expect(page.locator('.status-bar').getByRole('button', { name: 'PR #2' })).toBeVisible()
})

test('review a PR: diff, checks, logs, comment and merge', async ({ page }) => {
  await openShop(page)
  // Give the legacy branch a real change so the PR has a file to diff.
  await page.request.post(`${FAKE_GITHUB}/__move/feature/legacy`)

  await page.getByRole('button', { name: 'Pull Requests' }).click()
  await page.getByRole('list', { name: 'Pull requests' }).getByText('Legacy cleanup').click()
  await expect(page.getByRole('heading', { name: /Legacy cleanup #1/ })).toBeVisible()
  await expect(page.locator('.markdown em', { hasText: 'old' })).toBeVisible()
  await expect(page.getByText('approved these changes')).toBeVisible()

  // Files changed opens a base-vs-head diff.
  await page.getByRole('list', { name: 'Files changed' }).getByText('README.md').click()
  await expect(page.getByRole('tab', { name: /README\.md \(diff\)/ })).toBeVisible()
  await expect(page.locator('.monaco-diff-editor').getByText('pushed by someone else')).toBeVisible()

  // A failing GitHub Actions check opens its cleaned-up log.
  await page.getByRole('tab', { name: /PR #1/ }).click()
  const checks = page.getByRole('list', { name: 'Checks' })
  await expect(checks.getByRole('button', { name: 'build' })).toBeVisible()
  await checks.getByRole('button', { name: 'test' }).click()
  await expect(page.getByRole('tab', { name: /Log: test/ })).toBeVisible()
  const log = page.locator('.editor-body .monaco-editor')
  await expect(log.getByText('ERROR: Process completed with exit code 1.')).toBeVisible()
  await expect(log.getByText('2026-10-01T')).toHaveCount(0)

  await page.getByRole('tab', { name: /PR #1/ }).click()
  await page.getByLabel('Comment').fill('Ship it')
  await page.getByRole('button', { name: 'Comment', exact: true }).click()
  await expect(page.locator('.timeline-item', { hasText: 'Ship it' })).toBeVisible()

  await page.getByLabel('Merge method').selectOption('merge')
  await page.getByRole('button', { name: 'Merge pull request' }).click()
  await page.getByRole('button', { name: 'Confirm merge into main' }).click()
  await expect(page.locator('.pr-state')).toHaveText('Merged')
})

test('a commit is refused when the branch moved since it was loaded', async ({ page }) => {
  await openShop(page)
  await editFile(page, 'app', 'page.tsx', '// edit\n')
  await page.request.post(`${FAKE_GITHUB}/__move/main`)

  await page.getByRole('button', { name: 'Source Control' }).click()
  await page.getByLabel('Commit message').fill('Edit page')
  await page.getByRole('button', { name: 'Commit to main' }).click()
  await expect(page.locator('.scm [role=alert]')).toContainText('Branch changed since you loaded it')
  // Edits are kept.
  await expect(page.getByRole('list', { name: 'Changes' }).getByText('page.tsx')).toBeVisible()
})

test('new files, deletions and discarding changes', async ({ page }) => {
  await openShop(page)
  await page.keyboard.press('Control+Shift+p')
  await page.getByPlaceholder('Type a command').fill('new file')
  await page.keyboard.press('Enter')
  await page.getByPlaceholder(/New file path/).fill('lib/util.ts')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('tab', { name: /util\.ts/ })).toBeVisible()

  const tree = page.getByRole('tree', { name: 'Files' })
  await tree.getByText('README.md').hover()
  await tree.getByRole('button', { name: 'Delete README.md' }).click()
  await expect(tree.getByRole('treeitem', { name: /README\.md D/ })).toBeVisible()

  await page.getByRole('button', { name: 'Source Control' }).click()
  const changes = page.getByRole('list', { name: 'Changes' })
  await expect(changes.locator('.change-A', { hasText: 'util.ts' })).toBeVisible()
  await expect(changes.locator('.change-D', { hasText: 'README.md' })).toBeVisible()
  await page.getByRole('button', { name: 'Source Control' }).click() // hide
  await page.getByRole('button', { name: 'Source Control' }).click() // show
  await changes.getByText('README.md').hover()
  await page.getByRole('button', { name: 'Discard README.md' }).click()
  await expect(changes.getByText('README.md')).toHaveCount(0)

  // Changes survive a reload.
  await page.reload()
  await page.getByRole('button', { name: 'Source Control' }).click()
  await expect(page.getByRole('list', { name: 'Changes' }).getByText('util.ts')).toBeVisible()
})

test('branches: create, CI status in the status bar, delete', async ({ page }) => {
  await openShop(page)
  await expect(page.getByRole('button', { name: 'Checks: failure' })).toBeVisible()
  await page.getByRole('button', { name: 'Checks: failure' }).click()
  await page.getByRole('option', { name: /test/ }).click()
  await expect(page.getByRole('tab', { name: /Log: test/ })).toBeVisible()

  await page.keyboard.press('Control+Shift+p')
  await page.getByPlaceholder('Type a command').fill('create branch')
  await page.keyboard.press('Enter')
  await page.getByPlaceholder(/New branch name/).fill('spike')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: '⎇ spike' })).toBeVisible()

  await page.getByRole('button', { name: '⎇ spike' }).click()
  await page.getByRole('option', { name: /^main/ }).click()
  page.once('dialog', (d) => d.accept())
  await page.keyboard.press('Control+Shift+p')
  await page.getByPlaceholder('Type a command').fill('delete branch')
  await page.keyboard.press('Enter')
  await page.getByRole('option', { name: 'spike' }).click()
  await expect(page.getByText('Deleted branch spike')).toBeVisible()
})
