import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useBranches } from '../api/hooks'
import { useWorkbench } from '../state/store'

/** Turns "feature/add-checkout" into "Add checkout", a reasonable default title. */
export function titleFromBranch(branch: string): string {
  const words = branch.split('/').pop()!.replace(/[-_]+/g, ' ').trim()
  return words ? words[0].toUpperCase() + words.slice(1) : branch
}

export function CreatePullRequest() {
  const queryClient = useQueryClient()
  const { repo, openTab, closeTab } = useWorkbench()
  const branches = useBranches(repo)
  const [head, setHead] = useState(repo && repo.ref !== repo.defaultBranch ? repo.ref : '')
  const [base, setBase] = useState(repo?.defaultBranch ?? '')
  const [title, setTitle] = useState(head ? titleFromBranch(head) : '')
  const [body, setBody] = useState('')
  const [draft, setDraft] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!repo) return <div className="editor-message">Open a repository first.</div>

  const create = async () => {
    setBusy(true)
    setError(null)
    try {
      const pr = await api.createPull(repo.owner, repo.name, { title: title.trim(), head, base, body, draft })
      await queryClient.invalidateQueries({ queryKey: ['pulls'] })
      closeTab('newPr')
      openTab({ id: `pr:${pr.number}`, kind: 'pr', number: pr.number })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const names = branches.data?.map((b) => b.name) ?? []

  return (
    <div className="pr-view">
      <h1>Create pull request</h1>
      <div className="form-row">
        <label>
          Base
          <select className="input" value={base} onChange={(e) => setBase(e.target.value)} aria-label="Base branch">
            {names.map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <span className="arrow">←</span>
        <label>
          Compare
          <select
            className="input"
            value={head}
            aria-label="Head branch"
            onChange={(e) => {
              setHead(e.target.value)
              if (!title) setTitle(titleFromBranch(e.target.value))
            }}
          >
            <option value="" disabled>
              Choose a branch
            </option>
            {names.map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
      </div>
      <label className="form-field">
        Title
        <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Title" />
      </label>
      <label className="form-field">
        Description
        <textarea
          className="input"
          rows={8}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          aria-label="Description"
          placeholder="Markdown supported"
        />
      </label>
      <label className="checkbox">
        <input type="checkbox" checked={draft} onChange={(e) => setDraft(e.target.checked)} />
        Create as draft
      </label>
      <div className="form-actions">
        {error && <span className="error">{error}</span>}
        <button className="button" disabled={busy || !head || !base || head === base || !title.trim()} onClick={create}>
          {busy ? 'Creating…' : 'Create pull request'}
        </button>
      </div>
    </div>
  )
}
