import { beforeEach, describe, expect, it } from 'vitest'
import { useWorkbench } from './store'

const repo = { owner: 'octo', name: 'app', ref: 'main', defaultBranch: 'main' }

describe('workbench store', () => {
  beforeEach(() => {
    useWorkbench.setState({ repo: null, tabs: [], activeTab: null })
  })

  it('opens each file once and activates it', () => {
    const s = useWorkbench.getState()
    s.openFile('a.py')
    s.openFile('b.py')
    s.openFile('a.py')
    const { tabs, activeTab } = useWorkbench.getState()
    expect(tabs.map((t) => t.id)).toEqual(['file:a.py', 'file:b.py'])
    expect(activeTab).toBe('file:a.py')
  })

  it('activates the neighbour when closing the active tab', () => {
    const s = useWorkbench.getState()
    s.openFile('a.py')
    s.openFile('b.py')
    s.openFile('c.py')
    s.setActiveTab('file:b.py')
    s.closeTab('file:b.py')
    expect(useWorkbench.getState().activeTab).toBe('file:c.py')
    s.closeTab('file:c.py')
    expect(useWorkbench.getState().activeTab).toBe('file:a.py')
    s.closeTab('file:a.py')
    expect(useWorkbench.getState().activeTab).toBeNull()
  })

  it('closes file tabs but keeps settings when switching repos', () => {
    const s = useWorkbench.getState()
    s.openSettings()
    s.openFile('a.py')
    s.openRepo(repo)
    expect(useWorkbench.getState().tabs.map((t) => t.id)).toEqual(['settings'])
  })
})
