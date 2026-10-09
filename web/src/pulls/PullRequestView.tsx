import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, type Check, type MergeMethod, type Pull, type PullFile } from '../api/client'
import { cleanLog } from '../editor/cleanLog'
import { useChecks, usePull, usePullFiles, usePullTimeline } from '../api/hooks'
import { useWorkbench } from '../state/store'
import { ChecksList } from './Checks'
import { markdownComponents } from '../editor/markdown'

const STATUS_LETTER: Record<string, string> = {
  added: 'A',
  removed: 'D',
  modified: 'M',
  renamed: 'R',
  copied: 'C',
  changed: 'M',
}

function prState(pull: Pull): { label: string; className: string } {
  if (pull.merged) return { label: 'Merged', className: 'merged' }
  if (pull.state === 'closed') return { label: 'Closed', className: 'closed' }
  if (pull.draft) return { label: 'Draft', className: 'draft' }
  return { label: 'Open', className: 'open' }
}

function FileRow({ pull, file }: { pull: Pull; file: PullFile }) {
  const openTab = useWorkbench((s) => s.openTab)
  const open = () =>
    openTab({
      id: `prdiff:${pull.number}:${file.filename}`,
      kind: 'diff',
      title: file.filename.split('/').pop()!,
      base:
        file.status === 'added'
          ? null
          : { ref: pull.merge_base_sha, path: file.previous_filename ?? file.filename },
      head: file.status === 'removed' ? null : { ref: pull.head_sha, path: file.filename },
    })
  const letter = STATUS_LETTER[file.status] ?? 'M'
  return (
    <li className={`list-row change-${letter}`} onClick={open} title={file.filename}>
      <span className="list-main">
        {file.previous_filename ? `${file.previous_filename} → ` : ''}
        {file.filename}
      </span>
      <span className="diffstat">
        <span className="plus">+{file.additions}</span> <span className="minus">−{file.deletions}</span>
      </span>
      <span className="change-badge">{letter}</span>
    </li>
  )
}

function MergeBox({ pull }: { pull: Pull }) {
  const queryClient = useQueryClient()
  const repo = useWorkbench((s) => s.repo)!
  const [method, setMethod] = useState<MergeMethod>('squash')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (pull.state !== 'open') return null
  const blocked = pull.draft
    ? 'Draft pull requests can’t be merged.'
    : pull.mergeable === false
      ? 'This branch has conflicts that must be resolved on GitHub or locally.'
      : null

  const merge = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.merge(repo.owner, repo.name, pull.number, method)
      await Promise.all(
        [['pull'], ['pulls'], ['branches'], ['tree'], ['timeline']].map((queryKey) =>
          queryClient.invalidateQueries({ queryKey }),
        ),
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      setConfirming(false)
    }
  }

  return (
    <section className="pr-section merge-box">
      {blocked ? (
        <p className="muted">{blocked}</p>
      ) : (
        <div className="merge-row">
          <select
            className="input"
            aria-label="Merge method"
            value={method}
            onChange={(e) => {
              setMethod(e.target.value as MergeMethod)
              setConfirming(false)
            }}
          >
            <option value="squash">Squash and merge</option>
            <option value="merge">Create a merge commit</option>
            <option value="rebase">Rebase and merge</option>
          </select>
          {confirming ? (
            <>
              <button className="button danger" disabled={busy} onClick={merge}>
                {busy ? 'Merging…' : `Confirm merge into ${pull.base_ref}`}
              </button>
              <button className="button secondary" onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </>
          ) : (
            <button className="button" onClick={() => setConfirming(true)}>
              Merge pull request
            </button>
          )}
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}

function Conversation({ pull }: { pull: Pull }) {
  const queryClient = useQueryClient()
  const repo = useWorkbench((s) => s.repo)!
  const timeline = usePullTimeline(repo, pull.number)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const send = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.addComment(repo.owner, repo.name, pull.number, draft.trim())
      setDraft('')
      await queryClient.invalidateQueries({ queryKey: ['timeline', repo.owner, repo.name, pull.number] })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="pr-section">
      <h2>Conversation</h2>
      {timeline.isLoading && <p className="muted">Loading…</p>}
      {timeline.error && <p className="error">{timeline.error.message}</p>}
      {timeline.data?.length === 0 && <p className="muted">No comments yet.</p>}
      <ol className="timeline">
        {timeline.data?.map((item) => (
          <li key={item.id} className="timeline-item">
            <div className="timeline-meta">
              <strong>{item.author}</strong>{' '}
              {item.kind === 'review'
                ? `${item.state?.toLowerCase().replace('_', ' ')} these changes`
                : item.kind === 'review_comment'
                  ? `commented on ${item.path}${item.line ? `:${item.line}` : ''}`
                  : 'commented'}{' '}
              · <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time>
            </div>
            {item.body && (
              <div className="markdown">
                <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{item.body}</Markdown>
              </div>
            )}
          </li>
        ))}
      </ol>
      <textarea
        className="input"
        rows={3}
        placeholder="Leave a comment"
        aria-label="Comment"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      <div className="form-actions">
        {error && <span className="error">{error}</span>}
        <button className="button" disabled={!draft.trim() || busy} onClick={send}>
          Comment
        </button>
      </div>
    </section>
  )
}

/** Opens the new-task form, prefilled to fix a failing check on the PR's own branch. */
async function fixWithAgent(pull: Pull, check: Check) {
  const s = useWorkbench.getState()
  let tail = ''
  try {
    const log = cleanLog(await api.checkLogs(s.repo!.owner, s.repo!.name, check.id))
    tail = log.trimEnd().split('\n').slice(-120).join('\n')
  } catch {
    // Without the log the agent can still run the checks itself.
  }
  const prompt =
    `The CI check "${check.name}" is failing on pull request #${pull.number} (${pull.title}). ` +
    'Find the cause and fix it, then run the relevant checks to confirm.' +
    (tail ? `\n\nEnd of the failing log:\n\`\`\`\n${tail}\n\`\`\`` : '')
  useWorkbench.setState({ newTaskDraft: { prompt, baseBranch: pull.head_ref, prNumber: pull.number } })
  s.closeTab('newTask')
  s.openTab({ id: 'newTask', kind: 'newTask' })
}

export function PullRequestView({ number }: { number: number }) {
  const { repo, setRef } = useWorkbench()
  const pull = usePull(repo, number)
  const files = usePullFiles(repo, number, pull.data?.head_sha)
  const checks = useChecks(repo, pull.data?.head_sha)

  if (pull.isLoading) return <div className="editor-message">Loading pull request…</div>
  if (pull.error) return <div className="editor-message error">{pull.error.message}</div>
  if (!pull.data || !repo) return null
  const p = pull.data
  const state = prState(p)
  const sameRepo = p.head_repo === `${repo.owner}/${repo.name}`

  return (
    <div className="pr-view">
      <header className="pr-header">
        <h1>
          {p.title} <span className="muted">#{p.number}</span>
        </h1>
        <div className="pr-meta">
          <span className={`pr-state ${state.className}`}>{state.label}</span>
          <span>
            {p.author} wants to merge <code>{p.head_ref}</code> into <code>{p.base_ref}</code>
          </span>
          <span className="diffstat">
            <span className="plus">+{p.additions}</span> <span className="minus">−{p.deletions}</span>
          </span>
          {sameRepo && p.state === 'open' && repo.ref !== p.head_ref && (
            <button className="button secondary" onClick={() => setRef(p.head_ref)}>
              Check out branch
            </button>
          )}
          <a className="link-button" href={p.html_url} target="_blank" rel="noreferrer">
            Open on GitHub
          </a>
        </div>
      </header>

      <section className="pr-section markdown">
        {p.body ? <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{p.body}</Markdown> : <p className="muted">No description.</p>}
      </section>

      <section className="pr-section">
        <h2>Checks</h2>
        {checks.isLoading && <p className="muted">Loading…</p>}
        {checks.error && <p className="error">{checks.error.message}</p>}
        {checks.data && (
          <ChecksList checks={checks.data} onFix={p.state === 'open' && sameRepo ? (c) => fixWithAgent(p, c) : undefined} />
        )}
      </section>

      <MergeBox pull={p} />

      <section className="pr-section">
        <h2>Files changed {files.data && <span className="muted">({files.data.length})</span>}</h2>
        {files.isLoading && <p className="muted">Loading…</p>}
        {files.error && <p className="error">{files.error.message}</p>}
        <ul className="list" aria-label="Files changed">
          {files.data?.map((f) => <FileRow key={f.filename} pull={p} file={f} />)}
        </ul>
      </section>

      <Conversation pull={p} />
    </div>
  )
}
