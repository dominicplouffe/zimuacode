import type { QueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useWorkbench } from '../state/store'

export interface Command {
  id: string
  title: string
  keybinding?: string
  run: () => void
}

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
export const MOD = isMac ? '⌘' : 'Ctrl+'

export function getCommands(queryClient: QueryClient): Command[] {
  const s = useWorkbench.getState()
  return [
    { id: 'files.quickOpen', title: 'Go to File…', keybinding: `${MOD}P`, run: () => s.setPalette('files') },
    { id: 'repo.open', title: 'Open Repository…', run: () => s.setPalette('repos') },
    { id: 'repo.switchBranch', title: 'Switch Branch…', run: () => s.setPalette('branches') },
    { id: 'files.new', title: 'New File…', run: () => s.setPalette('newFile') },
    { id: 'git.createBranch', title: 'Create Branch…', run: () => s.setPalette('newBranch') },
    { id: 'git.deleteBranch', title: 'Delete Branch…', run: () => s.setPalette('deleteBranch') },
    { id: 'git.showChecks', title: 'Show Checks for Current Branch', run: () => s.setPalette('checks') },
    { id: 'pr.create', title: 'Create Pull Request', run: () => s.openTab({ id: 'newPr', kind: 'newPr' }) },
    { id: 'workbench.showScm', title: 'View: Show Source Control', run: () => useWorkbench.setState({ sidebar: 'scm', sidebarVisible: true }) },
    { id: 'workbench.showPulls', title: 'View: Show Pull Requests', run: () => useWorkbench.setState({ sidebar: 'pulls', sidebarVisible: true }) },
    { id: 'workbench.selectTheme', title: 'Preferences: Color Theme', run: () => s.setPalette('themes') },
    { id: 'workbench.openSettings', title: 'Preferences: Open Settings (JSON)', keybinding: `${MOD},`, run: s.openSettings },
    { id: 'workbench.toggleSidebar', title: 'View: Toggle Sidebar', keybinding: `${MOD}B`, run: s.toggleSidebar },
    { id: 'workbench.showExplorer', title: 'View: Show Explorer', run: () => useWorkbench.setState({ sidebar: 'explorer', sidebarVisible: true }) },
    {
      id: 'workbench.closeTab',
      title: 'View: Close Editor',
      run: () => {
        const { activeTab, closeTab } = useWorkbench.getState()
        if (activeTab) closeTab(activeTab)
      },
    },
    {
      id: 'repo.refresh',
      title: 'Refresh',
      run: () => {
        for (const queryKey of [['tree'], ['branches'], ['pulls'], ['checks']])
          queryClient.invalidateQueries({ queryKey })
      },
    },
    {
      id: 'auth.signOut',
      title: 'Sign Out',
      run: async () => {
        await api.logout()
        queryClient.clear()
        window.location.reload()
      },
    },
  ]
}
