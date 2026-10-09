// Electron shell: a window onto the hosted Zimua server. The server serves the web app,
// so the browser and desktop builds share one codebase and one session cookie flow.
const { app, BrowserWindow, shell } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

function serverUrl() {
  if (process.env.ZIMUA_SERVER_URL) return process.env.ZIMUA_SERVER_URL
  try {
    const config = JSON.parse(fs.readFileSync(path.join(app.getPath('userData'), 'config.json'), 'utf8'))
    if (config.serverUrl) return config.serverUrl
  } catch {
    // No config yet; fall back to a local server.
  }
  return 'http://localhost:8000'
}

// Navigation stays in the window for the server and GitHub's sign-in pages; anything else
// opens in the default browser.
function isAllowed(url, origin) {
  const target = new URL(url)
  return target.origin === origin || target.origin === 'https://github.com'
}

function createWindow() {
  const url = serverUrl()
  const origin = new URL(url).origin
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    title: 'Zimua Code',
    webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false },
  })

  win.webContents.setWindowOpenHandler(({ url: target }) => {
    shell.openExternal(target)
    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', (event, target) => {
    if (!isAllowed(target, origin)) {
      event.preventDefault()
      shell.openExternal(target)
    }
  })

  win.loadURL(url)
}

app.whenReady().then(() => {
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
