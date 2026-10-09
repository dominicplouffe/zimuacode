import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, api } from '../api/client'
import { useBranchPull, useTree } from '../api/hooks'
import { useWorkbench } from '../state/store'
import { branchKey, changeKind, useBranchChanges, useWorkingCopy } from '../state/workingCopy'

export function SourceControl() {
  const queryClient = useQueryClient()
  const { repo, setPalette, openTab, setRef } = useWorkbench()
  const tree = useTree(repo)
  const branchPull = useBranchPull(repo)
  const key = repo ? branchKey(repo) : null
  const changes = useBranchChanges(key)
  const { discard, clear } = useWorkingCopy()
  const [message, setMessage] = useState('')
  const [toNewBranch, setToNewBranch] = useState(false)
  const [newBranch, setNewBranch] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!repo || !key) return <div className="sidebar-empty">Open a repository to see changes.</div>

  const isDefault = repo.ref === repo.defaultBranch
  const target = toNewBranch ? newBranch.trim() : repo.ref
  const canCommit = changes.length > 0 && message.trim() !== '' && target !== '' && !busy && tree.data

  const commit = async () => {
    if (!tree.data) return
    setBusy(true)
    setError(null)
    try {
      await api.commit(repo.owner, repo.name, {
        branch: target,
        expected_head: tree.data.commit_sha,
        message: message.trim(),
        changes: changes.map((c) => ({ path: c.path, content: c.content })),
        create_branch: toNewBranch,
      })
      clear(key)
      setMessage('')
      setNewBranch('')
      setToNewBranch(false)
      await queryClient.invalidateQueries({ queryKey: ['branches'] })
      await queryClient.invalidateQueries({ queryKey: ['pulls'] })
      if (target !== repo.ref) setRef(target)
      else await queryClient.invalidateQueries({ queryKey: ['tree'] })
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const reload = () => queryClient.invalidateQueries({ queryKey: ['tree'] })

  return (
    <div className="scm">
      <div className="sidebar-section-header">
        <span>Source Control</span>
      </div>
      <div className="scm-form">
        <textarea
          className="input"
          placeholder={`Message (commit to ${target || 'new branch'})`}
          aria-label="Commit message"
          rows={3}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && canCommit) commit()
          }}
        />
        <label className="checkbox">
          <input type="checkbox" checked={toNewBranch} onChange={(e) => setToNewBranch(e.target.checked)} />
          Commit to a new branch
        </label>
        {toNewBranch && (
          <input
            className="input"
            placeholder="New branch name"
            aria-label="New branch name"
            value={newBranch}
            onChange={(e) => setNewBranch(e.target.value)}
          />
        )}
        {isDefault && !toNewBranch && changes.length > 0 && (
          <div className="sidebar-note">You're on the default branch. Consider a new branch.</div>
        )}
        <button className="button full" disabled={!canCommit} onClick={commit}>
          {busy ? 'Committing…' : `Commit to ${target || '…'}`}
        </button>
        {error && (
          <div className="sidebar-note error" role="alert">
            {error}
            {error.startsWith('Branch changed') && (
              <button className="link-button" onClick={reload}>
                Reload branch
              </button>
            )}
          </div>
        )}
        {changes.length === 0 && !isDefault && branchPull.isSuccess && !branchPull.data && (
          <button className="button full secondary" onClick={() => openTab({ id: 'newPr', kind: 'newPr' })}>
            Create Pull Request
          </button>
        )}
      </div>

      <div className="sidebar-section-header">
        <span>Changes</span>
        <span className="count">{changes.length}</span>
      </div>
      {changes.length === 0 && <div className="sidebar-note">No uncommitted changes.</div>}
      <ul className="list" aria-label="Changes">
        {changes.map((c) => {
          const kind = changeKind(c)
          const name = c.path.split('/').pop()
          return (
            <li
              key={c.path}
              className={`list-row change-${kind}`}
              title={c.path}
              onClick={() => openTab({ id: `wdiff:${c.path}`, kind: 'workingDiff', path: c.path })}
            >
              <span className="list-main">
                {name} <span className="list-detail">{c.path}</span>
              </span>
              <button
                className="row-action"
                title="Discard change"
                aria-label={`Discard ${c.path}`}
                onClick={(e) => {
                  e.stopPropagation()
                  discard(key, c.path)
                }}
              >
                ↺
              </button>
              <span className="change-badge">{kind}</span>
            </li>
          )
        })}
      </ul>

      <div className="sidebar-section-header">
        <span>Branch</span>
      </div>
      <div className="scm-actions">
        <button className="link-button" onClick={() => setPalette('branches')}>
          Switch branch…
        </button>
        <button className="link-button" onClick={() => setPalette('newBranch')}>
          Create branch…
        </button>
        {branchPull.data && (
          <button
            className="link-button"
            onClick={() => openTab({ id: `pr:${branchPull.data!.number}`, kind: 'pr', number: branchPull.data!.number })}
          >
            View PR #{branchPull.data.number}
          </button>
        )}
      </div>
    </div>
  )
}
