import { useEffect, useMemo } from 'react'
import { Group, Panel, Separator } from 'react-resizable-panels'
import { useEffectiveSettings, useThemes } from '../api/hooks'
import { Palette } from '../commands/Palette'
import { monaco } from '../editor/monaco'
import { Explorer } from '../panels/Explorer'
import { PullRequests } from '../panels/PullRequests'
import { SourceControl } from '../panels/SourceControl'
import { Tasks } from '../panels/Tasks'
import { TerminalPanel } from '../tasks/TerminalPanel'
import { api } from '../api/client'
import { useWorkbench } from '../state/store'
import { monacoThemeId, themeCssVars, toMonacoTheme } from '../theme/theme'
import { ActivityBar } from './ActivityBar'
import { EditorArea } from './EditorArea'
import { StatusBar } from './StatusBar'
import { Toast } from './Toast'

function useTheme(): string {
  const settings = useEffectiveSettings()
  const themes = useThemes()
  const wanted = (settings?.['workbench.theme'] as string | undefined) ?? 'dark'
  const theme = useMemo(
    () => themes.data?.find((t) => t.id === wanted) ?? themes.data?.find((t) => t.id === 'dark'),
    [themes.data, wanted],
  )

  useEffect(() => {
    if (!theme) return
    const root = document.documentElement
    for (const [name, value] of Object.entries(themeCssVars(theme))) root.style.setProperty(name, value)
    root.dataset.themeType = theme.type
    monaco.editor.defineTheme(monacoThemeId(theme), toMonacoTheme(theme))
    monaco.editor.setTheme(monacoThemeId(theme))
  }, [theme])

  return theme ? monacoThemeId(theme) : 'vs-dark'
}

function useKeybindings() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return
      const s = useWorkbench.getState()
      const key = e.key.toLowerCase()
      let handled = true
      if (key === 'p' && e.shiftKey) s.setPalette(s.palette === 'commands' ? null : 'commands')
      else if (key === 'p') s.setPalette(s.palette === 'files' ? null : 'files')
      else if (key === 'b' && !e.shiftKey) s.toggleSidebar()
      else if (key === ',') s.openSettings()
      else if (e.key === '`') {
        // Toggle the terminal for the task in the active tab.
        const tab = s.tabs.find((t) => t.id === s.activeTab)
        const taskId = tab?.kind === 'task' ? tab.taskId : null
        useWorkbench.setState({ terminalTask: s.terminalTask ? null : taskId })
      }
      else if (key === 's') {
        // Edits are kept automatically; just keep the browser's "save page" dialog away.
        // Not stopped, so the settings editor still sees it.
        e.preventDefault()
        return
      } else handled = false
      if (handled) {
        // Capture phase, so this wins over Monaco and the browser (print, bookmarks).
        e.preventDefault()
        e.stopPropagation()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [])
}

/** Notifications link to #task=<id> or #pr=<owner>/<name>/<number>. */
function useHashLinks() {
  useEffect(() => {
    const open = async () => {
      const hash = new URLSearchParams(location.hash.slice(1))
      const s = useWorkbench.getState()
      const task = hash.get('task')
      const pr = hash.get('pr')
      if (task) {
        s.openTab({ id: `task:${task}`, kind: 'task', taskId: task })
      } else if (pr) {
        const [owner, name, number] = pr.split('/')
        if (s.repo?.owner !== owner || s.repo?.name !== name) {
          try {
            const repo = await api.repo(owner, name)
            s.openRepo({ owner, name, ref: repo.default_branch, defaultBranch: repo.default_branch })
          } catch {
            return
          }
        }
        useWorkbench.getState().openTab({ id: `pr:${number}`, kind: 'pr', number: Number(number) })
      } else {
        return
      }
      history.replaceState(null, '', location.pathname + location.search)
    }
    open()
    window.addEventListener('hashchange', open)
    return () => window.removeEventListener('hashchange', open)
  }, [])
}

export function Workbench() {
  const sidebarVisible = useWorkbench((s) => s.sidebarVisible)
  const sidebar = useWorkbench((s) => s.sidebar)
  const terminalTask = useWorkbench((s) => s.terminalTask)
  const monacoTheme = useTheme()
  useKeybindings()
  useHashLinks()

  return (
    <div className="workbench">
      <div className="workbench-main">
        <ActivityBar />
        <Group orientation="horizontal" className="workbench-panels">
          {sidebarVisible && (
            <>
              <Panel id="sidebar" defaultSize={260} minSize={160} maxSize="60%" className="sidebar">
                {sidebar === 'explorer' && <Explorer />}
                {sidebar === 'scm' && <SourceControl />}
                {sidebar === 'pulls' && <PullRequests />}
                {sidebar === 'tasks' && <Tasks />}
              </Panel>
              <Separator className="separator" />
            </>
          )}
          <Panel id="editor" minSize={200}>
            {terminalTask ? (
              <Group orientation="vertical">
                <Panel id="editor-main" minSize={120}>
                  <EditorArea monacoTheme={monacoTheme} />
                </Panel>
                <Separator className="separator horizontal" />
                <Panel id="terminal" defaultSize={260} minSize={80}>
                  <TerminalPanel />
                </Panel>
              </Group>
            ) : (
              <EditorArea monacoTheme={monacoTheme} />
            )}
          </Panel>
        </Group>
      </div>
      <StatusBar />
      <Palette />
      <Toast />
    </div>
  )
}
