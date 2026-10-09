import { create } from 'zustand'

export interface RepoRef {
  owner: string
  name: string
  ref: string
  defaultBranch: string
}

export type Tab = { id: string; kind: 'file'; path: string } | { id: 'settings'; kind: 'settings' }

export type SidebarView = 'explorer'
export type Palette = 'files' | 'commands' | 'repos' | 'branches' | 'themes' | null

interface WorkbenchState {
  repo: RepoRef | null
  tabs: Tab[]
  activeTab: string | null
  sidebar: SidebarView
  sidebarVisible: boolean
  palette: Palette
  openRepo: (repo: RepoRef) => void
  setRef: (ref: string) => void
  openFile: (path: string) => void
  openSettings: () => void
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

  openRepo: (repo) => {
    saveLastRepo(repo)
    const tabs = get().tabs.filter((t) => t.kind !== 'file')
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
  openFile: (path) => {
    const id = fileTabId(path)
    const { tabs } = get()
    set({
      tabs: tabs.some((t) => t.id === id) ? tabs : [...tabs, { id, kind: 'file', path }],
      activeTab: id,
    })
  },
  openSettings: () => {
    const { tabs } = get()
    set({
      tabs: tabs.some((t) => t.id === 'settings') ? tabs : [...tabs, { id: 'settings', kind: 'settings' }],
      activeTab: 'settings',
    })
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
