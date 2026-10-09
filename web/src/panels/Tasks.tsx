import { useState } from 'react'
import { useTasks } from '../api/hooks'
import { useWorkbench } from '../state/store'
import { STATUS_LABEL } from '../tasks/TaskView'

export function Tasks() {
  const { repo, openTab } = useWorkbench()
  const [allRepos, setAllRepos] = useState(false)
  const tasks = useTasks(allRepos ? null : repo)

  return (
    <div>
      <div className="sidebar-section-header">
        <span>Agent tasks</span>
        <button
          className="header-action"
          title="New Task"
          aria-label="New Task"
          onClick={() => openTab({ id: 'newTask', kind: 'newTask' })}
        >
          +
        </button>
      </div>
      <div className="segmented" role="tablist" aria-label="Task scope">
        <button role="tab" aria-selected={!allRepos} className={!allRepos ? 'active' : ''} onClick={() => setAllRepos(false)}>
          This repo
        </button>
        <button role="tab" aria-selected={allRepos} className={allRepos ? 'active' : ''} onClick={() => setAllRepos(true)}>
          All repos
        </button>
      </div>
      {tasks.isLoading && <div className="sidebar-note">Loading…</div>}
      {tasks.error && <div className="sidebar-note error">{tasks.error.message}</div>}
      {tasks.data?.length === 0 && (
        <div className="sidebar-empty">
          <p>No tasks yet.</p>
          <button className="button" onClick={() => openTab({ id: 'newTask', kind: 'newTask' })}>
            New Task
          </button>
        </div>
      )}
      <ul className="list" aria-label="Tasks">
        {tasks.data?.map((t) => (
          <li
            key={t.id}
            className="list-row pr-row"
            title={t.title}
            onClick={() => openTab({ id: `task:${t.id}`, kind: 'task', taskId: t.id })}
          >
            <span className={`dot status-${t.status}`} aria-label={STATUS_LABEL[t.status] ?? t.status} />
            <span className="list-main">
              <span className="pr-title">{t.title}</span>
              <span className="list-detail">
                {STATUS_LABEL[t.status] ?? t.status}
                {allRepos ? ` · ${t.repo_name}` : ''} · {t.provider}
                {t.pr_number ? ` · PR #${t.pr_number}` : ''}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
