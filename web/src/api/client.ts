import type { components } from './schema'

type Schemas = components['schemas']
export type Me = Schemas['Me']
export type Repo = Schemas['Repo']
export type Branch = Schemas['Branch']
export type Tree = Schemas['Tree']
export type TreeEntry = Schemas['TreeEntry']
export type FileContent = Schemas['FileContent']
export type UserSettings = Schemas['UserSettings']
export type Theme = Schemas['Theme']

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

// The Electron shell and the browser both load the app from the server's origin, so
// relative URLs and the session cookie work everywhere.
async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers: {
      'x-zimua': '1',
      ...(body === undefined ? {} : { 'content-type': 'application/json' }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!resp.ok) {
    let message = resp.statusText
    try {
      const data = await resp.json()
      if (typeof data.detail === 'string') message = data.detail
    } catch {
      // Not JSON; keep the status text.
    }
    throw new ApiError(resp.status, message)
  }
  return resp.json() as Promise<T>
}

const repoPath = (owner: string, name: string) =>
  `/api/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`

export const api = {
  me: () => request<Me>('GET', '/api/auth/me'),
  logout: () => request<{ ok: boolean }>('POST', '/api/auth/logout'),
  repos: (page = 1) => request<Repo[]>('GET', `/api/repos?page=${page}`),
  repo: (owner: string, name: string) => request<Repo>('GET', repoPath(owner, name)),
  branches: (owner: string, name: string) =>
    request<Branch[]>('GET', `${repoPath(owner, name)}/branches`),
  tree: (owner: string, name: string, ref: string) =>
    request<Tree>('GET', `${repoPath(owner, name)}/tree?ref=${encodeURIComponent(ref)}`),
  file: (owner: string, name: string, path: string, ref: string) =>
    request<FileContent>(
      'GET',
      `${repoPath(owner, name)}/file?path=${encodeURIComponent(path)}&ref=${encodeURIComponent(ref)}`,
    ),
  settings: () => request<UserSettings>('GET', '/api/settings'),
  saveSettings: (raw: string) => request<UserSettings>('PUT', '/api/settings', { raw }),
  themes: () => request<Theme[]>('GET', '/api/themes'),
}
