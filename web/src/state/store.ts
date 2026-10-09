import { create } from 'zustand'

export interface RepoRef {
  owner: string
  name: string
  ref: string
  defaultBranch: string
}

/** One side of a diff between two commits; null when the file doesn't exist on that side. */
export type DiffSide = { ref: string; path: string } | null

export type Tab =
  | { id: string; kind: 'file'; path: string }
  | { id: 'settings'; kind: 'settings' }
  // An uncommitted change from the working copy, against what it was edited from.
  | { id: string; kind: 'workingDiff'; path: string }
  | { id: string; kind: 'diff'; title: string; base: DiffSide; head: DiffSide }
  | { id: string; kind: 'pr'; number: number }
  | { id: 'newPr'; kind: 'newPr' }
  | { id: string; kind: 'log'; jobId: number; title: string }

export type SidebarView = 'explorer' | 'scm' | 'pulls'
export type Palette =
  | 'files'
  | 'commands'
  | 'repos'
  | 'branches'
  | 'themes'
  | 'newFile'
  | 'newBranch'
  | 'deleteBranch'
  | 'checks'
  | null

interface WorkbenchState {
  repo: RepoRef | null
  tabs: Tab[]
  activeTab: string | null
  sidebar: SidebarView
  sidebarVisible: boolean
  palette: Palette
  toast: { message: string; error: boolean } | null
  notify: (message: string, error?: boolean) => void
  openRepo: (repo: RepoRef) => void
  setRef: (ref: string) => void
  openFile: (path: string) => void
  openSettings: () => void
  openTab: (tab: Tab) => void
  closeTab: (id: string) => void
  setActiveTab: (id: string) => void
  showSidebar: (view: SidebarView) => void
  toggleSidebar: () => void
  setPalette: (palette: Palette) => void
}

const LAST_REPO_KEY = 'zimua.lastRepo'

function loadLastRepo(): RepoRef | null {
  try {
    const raw = localStorage.getItem(LAST_REPO_KEY)
    return raw ? (JSON.parse(raw) as RepoRef) : null
  } catch {
    return null
  }
}

function saveLastRepo(repo: RepoRef): void {
  try {
    localStorage.setItem(LAST_REPO_KEY, JSON.stringify(repo))
  } catch {
    // Storage unavailable (private window); the last repo just won't be remembered.
  }
}

export const fileTabId = (path: string) => `file:${path}`

export const useWorkbench = create<WorkbenchState>((set, get) => ({
  repo: loadLastRepo(),
  tabs: [],
  activeTab: null,
  sidebar: 'explorer',
  sidebarVisible: true,
  palette: null,
  toast: null,

  notify: (message, error = false) => {
    const toast = { message, error }
    set({ toast })
    setTimeout(() => {
      if (get().toast === toast) set({ toast: null })
    }, error ? 8000 : 4000)
  },
  openRepo: (repo) => {
    saveLastRepo(repo)
    // Everything except settings belongs to the previous repo.
    const tabs = get().tabs.filter((t) => t.kind === 'settings')
    set({ repo, tabs, activeTab: tabs[0]?.id ?? null })
  },
  setRef: (ref) => {
    const repo = get().repo
    if (!repo) return
    const next = { ...repo, ref }
    saveLastRepo(next)
    // Open files keep their paths; their contents reload from the new ref.
    set({ repo: next })
  },
  openFile: (path) => get().openTab({ id: fileTabId(path), kind: 'file', path }),
  openSettings: () => get().openTab({ id: 'settings', kind: 'settings' }),
  openTab: (tab) => {
    const { tabs } = get()
    set({ tabs: tabs.some((t) => t.id === tab.id) ? tabs : [...tabs, tab], activeTab: tab.id })
  },
  closeTab: (id) => {
    const { tabs, activeTab } = get()
    const index = tabs.findIndex((t) => t.id === id)
    if (index < 0) return
    const next = tabs.filter((t) => t.id !== id)
    const neighbour = next[Math.min(index, next.length - 1)]
    set({ tabs: next, activeTab: activeTab === id ? (neighbour?.id ?? null) : activeTab })
  },
  setActiveTab: (id) => set({ activeTab: id }),
  showSidebar: (view) => {
    const { sidebar, sidebarVisible } = get()
    // Clicking the active view's icon hides the sidebar, as in VS Code.
    set({ sidebar: view, sidebarVisible: !(sidebarVisible && sidebar === view) })
  },
  toggleSidebar: () => set({ sidebarVisible: !get().sidebarVisible }),
  setPalette: (palette) => set({ palette }),
}))
