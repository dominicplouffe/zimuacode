import { useTasks } from '../api/hooks'
import { useWorkbench, type SidebarView } from '../state/store'
import { branchKey, useWorkingCopy } from '../state/workingCopy'

const Icon = ({ d }: { d: string }) => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
    <path d={d} strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const FILES = 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5'
// A branch: two commits on a line with a fork.
const SCM = 'M6 3v12M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9'
// A pull request: two branches joined by an arrow.
const PULLS = 'M6 3v12M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 15V8a2 2 0 0 0-2-2h-5M13 3l-3 3 3 3'
// A sparkle, for the agent.
const TASKS = 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z'
const GEAR =
  'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z'

const VIEWS: { id: SidebarView; label: string; icon: string }[] = [
  { id: 'explorer', label: 'Explorer', icon: FILES },
  { id: 'scm', label: 'Source Control', icon: SCM },
  { id: 'pulls', label: 'Pull Requests', icon: PULLS },
  { id: 'tasks', label: 'Agent Tasks', icon: TASKS },
]

export function ActivityBar() {
  const { sidebar, sidebarVisible, showSidebar, openSettings, repo } = useWorkbench()
  const running = useTasks(null).data?.filter((t) => t.status === 'running' || t.status === 'preparing').length ?? 0
  const changeCount = useWorkingCopy((s) => Object.keys((repo && s.changes[branchKey(repo)]) ?? {}).length)
  return (
    <nav className="activity-bar" aria-label="Views">
      {VIEWS.map((v) => (
        <button
          key={v.id}
          className={`activity-item${sidebarVisible && sidebar === v.id ? ' active' : ''}`}
          title={v.label}
          aria-label={v.label}
          onClick={() => showSidebar(v.id)}
        >
          <Icon d={v.icon} />
          {v.id === 'scm' && changeCount > 0 && <span className="activity-badge">{changeCount}</span>}
          {v.id === 'tasks' && running > 0 && <span className="activity-badge">{running}</span>}
        </button>
      ))}
      <div className="activity-spacer" />
      <button className="activity-item" title="Settings" aria-label="Settings" onClick={openSettings}>
        <Icon d={GEAR} />
      </button>
    </nav>
  )
}
