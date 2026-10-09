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
export type PullSummary = Schemas['PullSummary']
export type Pull = Schemas['Pull']
export type PullFile = Schemas['PullFile']
export type TimelineItem = Schemas['TimelineItem']
export type Check = Schemas['Check']
export type FileChange = Schemas['FileChange']
export type CommitResult = Schemas['CommitResult']
export type MergeMethod = Schemas['MergeRequest']['method']

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
async function send(method: string, path: string, body?: unknown): Promise<Response> {
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
  return resp
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await send(method, path, body)
  return (resp.status === 204 ? undefined : resp.json()) as Promise<T>
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
  createBranch: (owner: string, name: string, branch: string, fromSha: string) =>
    request<Branch>('POST', `${repoPath(owner, name)}/branches`, { name: branch, from_sha: fromSha }),
  deleteBranch: (owner: string, name: string, branch: string) =>
    request<void>('DELETE', `${repoPath(owner, name)}/branches?branch=${encodeURIComponent(branch)}`),
  commit: (
    owner: string,
    name: string,
    body: { branch: string; expected_head: string; message: string; changes: FileChange[]; create_branch: boolean },
  ) => request<CommitResult>('POST', `${repoPath(owner, name)}/commits`, body),
  pulls: (owner: string, name: string, state: 'open' | 'closed' | 'all', head?: string) =>
    request<PullSummary[]>(
      'GET',
      `${repoPath(owner, name)}/pulls?state=${state}${head ? `&head=${encodeURIComponent(head)}` : ''}`,
    ),
  pull: (owner: string, name: string, number: number) =>
    request<Pull>('GET', `${repoPath(owner, name)}/pulls/${number}`),
  pullFiles: (owner: string, name: string, number: number) =>
    request<PullFile[]>('GET', `${repoPath(owner, name)}/pulls/${number}/files`),
  pullTimeline: (owner: string, name: string, number: number) =>
    request<TimelineItem[]>('GET', `${repoPath(owner, name)}/pulls/${number}/timeline`),
  createPull: (
    owner: string,
    name: string,
    body: { title: string; head: string; base: string; body: string; draft: boolean },
  ) => request<PullSummary>('POST', `${repoPath(owner, name)}/pulls`, body),
  addComment: (owner: string, name: string, number: number, body: string) =>
    request<TimelineItem>('POST', `${repoPath(owner, name)}/pulls/${number}/comments`, { body }),
  merge: (owner: string, name: string, number: number, method: MergeMethod) =>
    request<Schemas['MergeResult']>('PUT', `${repoPath(owner, name)}/pulls/${number}/merge`, { method }),
  checks: (owner: string, name: string, ref: string) =>
    request<Check[]>('GET', `${repoPath(owner, name)}/checks?ref=${encodeURIComponent(ref)}`),
  checkLogs: async (owner: string, name: string, jobId: number) =>
    (await send('GET', `${repoPath(owner, name)}/checks/${jobId}/logs`)).text(),
  settings: () => request<UserSettings>('GET', '/api/settings'),
  saveSettings: (raw: string) => request<UserSettings>('PUT', '/api/settings', { raw }),
  themes: () => request<Theme[]>('GET', '/api/themes'),
}
