import { expect, test, type Page } from '@playwright/test'

const mod = process.platform === 'darwin' ? 'Meta' : 'Control'
const FAKE_GITHUB = 'http://localhost:9001'

test.beforeEach(async ({ request }) => {
  await request.post(`${FAKE_GITHUB}/__reset`)
})

async function signIn(page: Page) {
  const resp = await page.request.post('/api/auth/dev-login', { data: { token: 'fake' } })
  expect(resp.ok()).toBeTruthy()
}

async function openWorkbench(page: Page) {
  await page.goto('/')
  await expect(page.locator('.status-bar')).toBeVisible()
}

async function openShopRepo(page: Page) {
  await openWorkbench(page)
  await page.getByRole('button', { name: 'Open Repository' }).first().click()
  await page.getByPlaceholder('Open a repository').fill('shop')
  await page.getByRole('option', { name: /octo\/shop/ }).click()
}

test('shows the sign-in screen when signed out', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'Sign in with GitHub' })).toBeVisible()
})

test('opens a repo, browses files and opens them in the editor', async ({ page }) => {
  await signIn(page)
  await openShopRepo(page)

  const tree = page.getByRole('tree', { name: 'Files' })
  await tree.getByText('app', { exact: true }).click()
  await tree.getByText('page.tsx').click()
  await expect(page.getByRole('tab', { name: /page\.tsx/ })).toBeVisible()
  await expect(page.locator('.monaco-editor').getByText('Page()')).toBeVisible()

  await tree.getByText('public', { exact: true }).click()
  await tree.getByText('logo.png').click()
  await expect(page.getByText("This file is binary and can't be shown.")).toBeVisible()
})

test('quick open finds files by fuzzy name', async ({ page }) => {
  await signIn(page)
  await openShopRepo(page)
  await expect(page.getByRole('tree', { name: 'Files' }).getByText('README.md')).toBeVisible()
  await page.keyboard.press(`${mod}+p`)
  await page.getByPlaceholder('Search files by name').fill('srvpy')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('tab', { name: /server\.py/ })).toBeVisible()
})

test('switches branches from the status bar', async ({ page }) => {
  await signIn(page)
  await openShopRepo(page)
  await page.getByRole('button', { name: '⎇ main' }).click()
  await page.getByRole('option', { name: /feature\/checkout/ }).click()
  await expect(page.getByRole('button', { name: '⎇ feature/checkout' })).toBeVisible()
  await expect(page.getByRole('tree', { name: 'Files' }).getByText('checkout.tsx')).toBeHidden()
  await page.getByRole('tree', { name: 'Files' }).getByText('app', { exact: true }).click()
  await expect(page.getByRole('tree', { name: 'Files' }).getByText('checkout.tsx')).toBeVisible()
})

test('changes theme from the command palette and persists it', async ({ page }) => {
  await signIn(page)
  await openWorkbench(page)
  await page.keyboard.press(`${mod}+Shift+p`)
  await page.getByPlaceholder('Type a command').fill('color theme')
  await page.keyboard.press('Enter')
  await page.getByRole('option', { name: 'Light', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme-type', 'light')

  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme-type', 'light')
  const settings = await (await page.request.get('/api/settings')).json()
  expect(settings.effective['workbench.theme']).toBe('light')
})

test('edits settings.json with validation', async ({ page }) => {
  await signIn(page)
  await openWorkbench(page)
  await page.getByRole('button', { name: 'Settings' }).click()
  await expect(page.getByRole('tab', { name: /settings\.json/ })).toBeVisible()

  await page.locator('.settings-editor .monaco-editor .view-lines').click()
  await page.keyboard.press(`${mod}+a`)
  await page.keyboard.press('Delete')
  await page.keyboard.insertText('{"editor.fontSize": "huge"}')
  await page.keyboard.press(`${mod}+s`)
  await expect(page.locator('.settings-editor .error')).toContainText('editor.fontSize')

  await page.keyboard.press(`${mod}+a`)
  await page.keyboard.press('Delete')
  await page.keyboard.insertText('{"editor.fontSize": 18}')
  await page.keyboard.press(`${mod}+s`)
  await expect(page.locator('.settings-editor .error')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Save' })).toBeDisabled()
  const settings = await (await page.request.get('/api/settings')).json()
  expect(settings.effective['editor.fontSize']).toBe(18)
})
