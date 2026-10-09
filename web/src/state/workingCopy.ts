import { create } from 'zustand'

/** One uncommitted change. `original` null means a new file; `content` null means deleted. */
export interface Change {
  path: string
  content: string | null
  original: string | null
}

export type ChangeKind = 'M' | 'A' | 'D'

export function changeKind(c: Change): ChangeKind {
  if (c.original === null) return 'A'
  if (c.content === null) return 'D'
  return 'M'
}

/** Changes are kept per repo and branch: "owner/name@branch". */
export const branchKey = (repo: { owner: string; name: string; ref: string }) =>
  `${repo.owner}/${repo.name}@${repo.ref}`

type Changes = Record<string, Record<string, Change>>

interface WorkingCopyState {
  changes: Changes
  /** Records an edit. Editing back to the original drops the change. */
  edit: (key: string, path: string, original: string | null, content: string) => void
  create: (key: string, path: string) => void
  remove: (key: string, path: string, original: string) => void
  discard: (key: string, path: string) => void
  clear: (key: string) => void
}

const STORAGE_KEY = 'zimua.workingCopy'

function load(): Changes {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Changes) : {}
  } catch {
    return {}
  }
}

function save(changes: Changes): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(changes))
  } catch {
    // Storage full or unavailable: edits still live in memory until the page closes.
  }
}

function update(changes: Changes, key: string, path: string, change: Change | null): Changes {
  const branch = { ...(changes[key] ?? {}) }
  if (change) branch[path] = change
  else delete branch[path]
  const next = { ...changes, [key]: branch }
  if (Object.keys(branch).length === 0) delete next[key]
  save(next)
  return next
}

export const useWorkingCopy = create<WorkingCopyState>((set, get) => ({
  changes: load(),

  edit: (key, path, original, content) => {
    const existing = get().changes[key]?.[path]
    const base = existing ? existing.original : original
    const unchanged = base !== null && content === base
    set({ changes: update(get().changes, key, path, unchanged ? null : { path, original: base, content }) })
  },
  create: (key, path) => {
    if (get().changes[key]?.[path]) return
    set({ changes: update(get().changes, key, path, { path, original: null, content: '' }) })
  },
  remove: (key, path, original) => {
    const existing = get().changes[key]?.[path]
    // Deleting a file that was only ever added locally just forgets it.
    if (existing && existing.original === null) {
      set({ changes: update(get().changes, key, path, null) })
      return
    }
    set({ changes: update(get().changes, key, path, { path, original: existing?.original ?? original, content: null }) })
  },
  discard: (key, path) => set({ changes: update(get().changes, key, path, null) }),
  clear: (key) => {
    const next = { ...get().changes }
    delete next[key]
    save(next)
    set({ changes: next })
  },
}))

const EMPTY: Record<string, Change> = {}

/** The changes on one branch, sorted by path. */
export function useBranchChanges(key: string | null): Change[] {
  const branch = useWorkingCopy((s) => (key ? s.changes[key] : undefined) ?? EMPTY)
  return Object.values(branch).sort((a, b) => a.path.localeCompare(b.path))
}
