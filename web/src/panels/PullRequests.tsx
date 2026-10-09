import { useState } from 'react'
import { usePulls } from '../api/hooks'
import { useWorkbench } from '../state/store'

export function PullRequests() {
  const { repo, openTab } = useWorkbench()
  const [state, setState] = useState<'open' | 'closed'>('open')
  const pulls = usePulls(repo, state)

  if (!repo) return <div className="sidebar-empty">Open a repository to see its pull requests.</div>

  return (
    <div>
      <div className="sidebar-section-header">
        <span>Pull Requests</span>
        <button
          className="header-action"
          title="Create Pull Request"
          aria-label="Create Pull Request"
          onClick={() => openTab({ id: 'newPr', kind: 'newPr' })}
        >
          +
        </button>
      </div>
      <div className="segmented" role="tablist" aria-label="Pull request state">
        {(['open', 'closed'] as const).map((s) => (
          <button key={s} role="tab" aria-selected={state === s} className={state === s ? 'active' : ''} onClick={() => setState(s)}>
            {s === 'open' ? 'Open' : 'Closed'}
          </button>
        ))}
      </div>
      {pulls.isLoading && <div className="sidebar-note">Loading…</div>}
      {pulls.error && <div className="sidebar-note error">{pulls.error.message}</div>}
      {pulls.data?.length === 0 && <div className="sidebar-note">No {state} pull requests.</div>}
      <ul className="list" aria-label="Pull requests">
        {pulls.data?.map((p) => (
          <li
            key={p.number}
            className="list-row pr-row"
            title={p.title}
            onClick={() => openTab({ id: `pr:${p.number}`, kind: 'pr', number: p.number })}
          >
            <span className="list-main">
              <span className="pr-title">{p.title}</span>
              <span className="list-detail">
                #{p.number} · {p.author} · {p.head_ref}
                {p.draft ? ' · draft' : ''}
                {p.merged ? ' · merged' : ''}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
