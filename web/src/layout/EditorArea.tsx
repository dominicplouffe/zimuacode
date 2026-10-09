import { RefDiffView, WorkingDiffView } from '../editor/DiffView'
import { FileEditor } from '../editor/FileEditor'
import { LogView } from '../editor/LogView'
import { SettingsEditor } from '../editor/SettingsEditor'
import { MOD } from '../commands/commands'
import { CreatePullRequest } from '../pulls/CreatePullRequest'
import { PullRequestView } from '../pulls/PullRequestView'
import { Accounts } from '../tasks/Accounts'
import { NewTask } from '../tasks/NewTask'
import { TaskDiffView } from '../tasks/TaskDiffView'
import { TaskView } from '../tasks/TaskView'
import { useTask } from '../api/hooks'
import { useWorkbench, type Tab } from '../state/store'
import { branchKey, useWorkingCopy } from '../state/workingCopy'

const basename = (path: string) => path.split('/').pop()!

export function tabTitle(tab: Tab, taskTitle?: string): string {
  switch (tab.kind) {
    case 'file':
      return basename(tab.path)
    case 'settings':
      return 'settings.json'
    case 'workingDiff':
      return `${basename(tab.path)} (changes)`
    case 'diff':
      return `${tab.title} (diff)`
    case 'pr':
      return `PR #${tab.number}`
    case 'newPr':
      return 'New pull request'
    case 'log':
      return `Log: ${tab.title}`
    case 'task': {
      const title = taskTitle ?? 'Task'
      return title.length > 28 ? title.slice(0, 27) + '…' : title
    }
    case 'newTask':
      return 'New task'
    case 'taskDiff':
      return `${basename(tab.path)} (agent)`
    case 'accounts':
      return 'Agent accounts'
  }
}

function tabTooltip(tab: Tab): string {
  if (tab.kind === 'file' || tab.kind === 'workingDiff' || tab.kind === 'taskDiff') return tab.path
  if (tab.kind === 'diff') return tab.head?.path ?? tab.base?.path ?? tab.title
  return tabTitle(tab)
}

function TaskTabLabel({ taskId }: { taskId: string }) {
  const task = useTask(taskId)
  const status = task.data?.status
  return (
    <>
      {status && <span className={`dot status-${status}`} />}
      <span>{tabTitle({ id: taskId, kind: 'task', taskId }, task.data?.title)}</span>
    </>
  )
}

export function EditorArea({ monacoTheme }: { monacoTheme: string }) {
  const { tabs, activeTab, setActiveTab, closeTab, repo } = useWorkbench()
  const changed = useWorkingCopy((s) => (repo ? s.changes[branchKey(repo)] : undefined))
  const active = tabs.find((t) => t.id === activeTab)

  return (
    <div className="editor-area">
      {tabs.length > 0 && (
        <div className="tabs" role="tablist">
          {tabs.map((tab) => {
            const dirty = tab.kind === 'file' && changed?.[tab.path] !== undefined
            const title = tabTitle(tab)
            return (
              <div
                key={tab.id}
                role="tab"
                aria-selected={tab.id === activeTab}
                className={`tab${tab.id === activeTab ? ' active' : ''}`}
                title={tabTooltip(tab)}
                onClick={() => setActiveTab(tab.id)}
                onAuxClick={(e) => e.button === 1 && closeTab(tab.id)}
              >
                {tab.kind === 'task' ? <TaskTabLabel taskId={tab.taskId} /> : <span>{title}</span>}
                {dirty && (
                  <span className="tab-dirty" aria-label="modified">
                    ●
                  </span>
                )}
                <button
                  className="tab-close"
                  aria-label={`Close ${title}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    closeTab(tab.id)
                  }}
                >
                  ×
                </button>
              </div>
            )
          })}
        </div>
      )}
      <div className="editor-body">
        {active?.kind === 'file' && <FileEditor key={active.id} path={active.path} theme={monacoTheme} />}
        {active?.kind === 'settings' && <SettingsEditor theme={monacoTheme} />}
        {active?.kind === 'workingDiff' && <WorkingDiffView key={active.id} path={active.path} theme={monacoTheme} />}
        {active?.kind === 'diff' && (
          <RefDiffView key={active.id} id={active.id} base={active.base} head={active.head} theme={monacoTheme} />
        )}
        {active?.kind === 'pr' && <PullRequestView key={active.id} number={active.number} />}
        {active?.kind === 'newPr' && <CreatePullRequest />}
        {active?.kind === 'log' && <LogView key={active.id} jobId={active.jobId} theme={monacoTheme} />}
        {active?.kind === 'task' && <TaskView key={active.id} taskId={active.taskId} />}
        {active?.kind === 'newTask' && <NewTask />}
        {active?.kind === 'accounts' && <Accounts />}
        {active?.kind === 'taskDiff' && (
          <TaskDiffView key={active.id} taskId={active.taskId} path={active.path} theme={monacoTheme} />
        )}
        {!active && (
          <div className="welcome">
            <h1>Zimua Code</h1>
            <dl>
              <dt>Go to file</dt>
              <dd>{MOD}P</dd>
              <dt>Show all commands</dt>
              <dd>{MOD}⇧P</dd>
              <dt>Toggle sidebar</dt>
              <dd>{MOD}B</dd>
              <dt>Settings</dt>
              <dd>{MOD},</dd>
            </dl>
          </div>
        )}
      </div>
    </div>
  )
}
