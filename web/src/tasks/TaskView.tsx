import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, type TaskEvent, type TaskSummary } from '../api/client'
import { useProviders, useTask, useTaskChanges } from '../api/hooks'
import { markdownComponents } from '../editor/markdown'
import { useWorkbench } from '../state/store'
import { ImageStrip, SentImages, usePastedImages } from './images'
import { buildTranscript, summarizeTool, type Entry } from './transcript'
import { useTaskEvents } from './useTaskEvents'

const text = (event: TaskEvent) => String(event.data.text ?? '')

export const STATUS_LABEL: Record<string, string> = {
  preparing: 'Preparing',
  running: 'Working',
  idle: 'Waiting for you',
  failed: 'Failed',
  interrupted: 'Interrupted',
  stopped: 'Archived',
}

export function formatCost(task: Pick<TaskSummary, 'cost_usd' | 'input_tokens' | 'output_tokens'>): string {
  const tokens = task.input_tokens + task.output_tokens
  const k = tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}k` : String(tokens)
  return `${k} tokens${task.cost_usd ? ` · $${task.cost_usd.toFixed(2)}` : ''}`
}

function EventView({ event, taskId }: { event: TaskEvent; taskId: string }) {
  switch (event.type) {
    case 'user_message':
      return (
        <div className="msg msg-user">
          {event.data.queued ? <div className="msg-note">Queued until the agent finishes</div> : null}
          <div className="msg-text">{text(event)}</div>
          {Array.isArray(event.data.images) && <SentImages taskId={taskId} names={event.data.images as string[]} />}
        </div>
      )
    case 'assistant_text':
      return (
        <div className={`msg msg-assistant markdown${event.data.subagent ? ' subagent' : ''}`}>
          <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {text(event)}
          </Markdown>
        </div>
      )
    case 'thinking':
      return (
        <details className="msg msg-thinking">
          <summary>Thinking</summary>
          <div className="msg-text">{text(event)}</div>
        </details>
      )
    case 'command': {
      const code = event.data.exit_code as number | null | undefined
      return (
        <details className={`msg msg-tool${code ? ' is-error' : ''}`}>
          <summary>
            <span className="tool-name">$ {String(event.data.command ?? '')}</span>
            {code !== undefined && code !== null && <span className="muted"> exit {code}</span>}
          </summary>
          <pre>{String(event.data.output ?? '')}</pre>
        </details>
      )
    }
    case 'file_change': {
      const changes = (event.data.changes as { path: string; kind: string }[] | undefined) ?? []
      return (
        <div className="msg msg-tool">
          {changes.map((c) => (
            <div key={c.path}>
              <span className="tool-name">{c.kind === 'add' ? 'Added' : c.kind === 'delete' ? 'Deleted' : 'Edited'}</span>{' '}
              {c.path}
            </div>
          ))}
        </div>
      )
    }
    case 'todo': {
      const items = (event.data.items as { text: string; completed: boolean }[] | undefined) ?? []
      return (
        <ul className="msg msg-todo">
          {items.map((item, i) => (
            <li key={i} className={item.completed ? 'done' : ''}>
              {item.completed ? '☑' : '☐'} {item.text}
            </li>
          ))}
        </ul>
      )
    }
    case 'status': {
      const status = String(event.data.status)
      if (status === 'running' || status === 'preparing') {
        return event.data.detail ? <div className="msg-status muted">{String(event.data.detail)}…</div> : null
      }
      return (
        <div className={`msg-status status-${status}`}>
          {STATUS_LABEL[status] ?? status}
          {event.data.detail ? ` · ${String(event.data.detail)}` : ''}
        </div>
      )
    }
    case 'error':
      return (
        <div className="msg msg-error" role="alert">
          {String(event.data.message ?? 'Error')}
        </div>
      )
    case 'link':
      return null
    case 'round':
      return (
        <div className="msg-round" role="separator">
          PR #{String(event.data.previous_pr)} was merged. Continuing on a new branch from the latest{' '}
          {String(event.data.base)}.
        </div>
      )
    case 'pr':
      return (
        <div className="msg-status">
          {event.data.created ? 'Opened' : 'Updated'} pull request #{String(event.data.number)}
        </div>
      )
    default:
      return null
  }
}

function EntryView({ entry, taskId }: { entry: Entry; taskId: string }) {
  if (entry.kind === 'event') return <EventView event={entry.event} taskId={taskId} />
  if (entry.kind === 'logs') {
    return (
      <details className="msg msg-log">
        <summary>CLI output ({entry.events.length} lines)</summary>
        <pre>{entry.events.map(text).join('\n')}</pre>
      </details>
    )
  }
  const { call, result } = entry
  const isError = Boolean(result?.data.is_error)
  const summary = summarizeTool(String(call.data.name ?? 'tool'), call.data.input)
  return (
    <details className={`msg msg-tool${isError ? ' is-error' : ''}${call.data.subagent ? ' subagent' : ''}`}>
      <summary>
        <span className="tool-name">{summary}</span>
        {!result && <span className="muted"> running…</span>}
      </summary>
      <pre className="tool-input">{JSON.stringify(call.data.input, null, 2)}</pre>
      {result && <pre>{String(result.data.output ?? '')}</pre>}
    </details>
  )
}

function Composer({ task }: { task: TaskSummary }) {
  const queryClient = useQueryClient()
  const provider = useProviders().data?.find((p) => p.id === task.provider)
  const canInterrupt = provider?.capabilities.interrupt ?? true
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const pasted = usePastedImages(provider?.capabilities.images ?? true)
  const working = task.status === 'running' || task.status === 'preparing'
  const canSend = draft.trim() !== '' && task.status !== 'stopped'

  const send = async () => {
    setError(null)
    try {
      const sent = await api.sendMessage(task.id, draft.trim(), pasted.images.map((i) => i.data))
      console.log('[task-debug] sendMessage returned status =', sent.status)
      setDraft('')
      pasted.clear()
      queryClient.invalidateQueries({ queryKey: ['task', task.id] })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }
  const interrupt = async () => {
    setError(null)
    try {
      await api.interrupt(task.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="composer">
      <textarea
        className="input"
        rows={3}
        aria-label="Message the agent"
        placeholder={working ? 'Queue a follow-up for when the agent finishes' : 'Reply to the agent (⌘↵ to send)'}
        value={draft}
        disabled={task.status === 'stopped'}
        onChange={(e) => setDraft(e.target.value)}
        onPaste={pasted.onPaste}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && canSend) send()
        }}
      />
      <ImageStrip images={pasted.images} onRemove={pasted.remove} />
      <div className="form-actions">
        {(error ?? pasted.error) && <span className="error">{error ?? pasted.error}</span>}
        {task.status === 'running' && canInterrupt && (
          <button className="button secondary" onClick={interrupt}>
            Interrupt
          </button>
        )}
        <button className="button" disabled={!canSend} onClick={send}>
          {working ? 'Queue' : 'Send'}
        </button>
      </div>
    </div>
  )
}

/** The current PR's state on GitHub, to notice when it's been merged or closed. */
function useTaskPull(task: TaskSummary) {
  return useQuery({
    // Same key as usePull, so merging from the PR tab updates this too.
    queryKey: ['pull', task.repo_owner, task.repo_name, task.pr_number],
    queryFn: () => api.pull(task.repo_owner, task.repo_name, task.pr_number!),
    enabled: task.pr_number !== null,
  })
}

function PullLink({ number, label }: { number: number; label?: string }) {
  const openTab = useWorkbench((s) => s.openTab)
  return (
    <button className="link-button" onClick={() => openTab({ id: `pr:${number}`, kind: 'pr', number })}>
      {label ?? `PR #${number}`}
    </button>
  )
}

function Publish({ task }: { task: TaskSummary }) {
  const queryClient = useQueryClient()
  const openTab = useWorkbench((s) => s.openTab)
  const pull = useTaskPull(task)
  // A merged or closed PR ends the round: the next publish opens a new PR.
  const ended = pull.data && pull.data.state !== 'open' ? pull.data : null
  const [title, setTitle] = useState(task.round > 1 || task.pr_number ? '' : task.title)
  const [draft, setDraft] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const working = task.status === 'running' || task.status === 'preparing'

  const publish = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await api.publishTask(task.id, { title: title.trim(), body: '', draft })
      queryClient.invalidateQueries({ queryKey: ['pulls'] })
      queryClient.invalidateQueries({ queryKey: ['pull'] })
      queryClient.invalidateQueries({ queryKey: ['task', task.id] })
      queryClient.invalidateQueries({ queryKey: ['taskChanges', task.id] })
      if (result.created) openTab({ id: `pr:${result.pr_number}`, kind: 'pr', number: result.pr_number })
      else useWorkbench.getState().notify(`Pushed to PR #${result.pr_number}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="task-publish">
      {task.previous_prs.length > 0 && (
        <div className="muted">
          Earlier:{' '}
          {task.previous_prs.map((n, i) => (
            <span key={n}>
              {i > 0 && ', '}
              <PullLink number={n} />
            </span>
          ))}
        </div>
      )}
      {task.pr_number && !ended ? (
        <>
          <PullLink number={task.pr_number} label={`View PR #${task.pr_number}`} />
          <button className="button full" disabled={busy || working} onClick={publish}>
            {busy ? 'Pushing…' : 'Push changes to PR'}
          </button>
        </>
      ) : (
        <>
          {ended && (
            <div className="muted">
              <PullLink number={ended.number} /> was {ended.merged ? 'merged' : 'closed'}. New changes go to a new pull
              request{ended.merged ? `, on a fresh branch from ${ended.base_ref}` : ''}.
            </div>
          )}
          <input
            className="input"
            aria-label="Pull request title"
            placeholder="What does this change do?"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          {!task.branch_named || ended?.merged ? (
            <div className="muted">The branch is named after this title.</div>
          ) : null}
          <label className="checkbox">
            <input type="checkbox" checked={draft} onChange={(e) => setDraft(e.target.checked)} />
            Draft
          </label>
          <button className="button full" disabled={busy || working || !title.trim()} onClick={publish}>
            {busy ? 'Publishing…' : 'Create pull request'}
          </button>
        </>
      )}
      {working && <div className="muted">Available when the agent finishes.</div>}
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
    </div>
  )
}

function Preview({ task }: { task: TaskSummary }) {
  const [port, setPort] = useState('3000')
  const [error, setError] = useState<string | null>(null)
  const open = async () => {
    setError(null)
    // Open the window now, while the click still counts as a user gesture; popup blockers
    // would stop a window opened after the request.
    const win = window.open('about:blank', '_blank')
    try {
      const { url } = await api.preview(task.id, Number(port))
      if (win) win.location.href = url
      else window.location.href = url
    } catch (e) {
      win?.close()
      setError(e instanceof Error ? e.message : String(e))
    }
  }
  return (
    <div className="task-publish">
      <div className="merge-row">
        <input
          className="input"
          aria-label="Preview port"
          inputMode="numeric"
          value={port}
          onChange={(e) => setPort(e.target.value.replace(/\D/g, ''))}
          style={{ width: 90 }}
        />
        <button className="button secondary" disabled={!port} onClick={open}>
          Open preview
        </button>
      </div>
      <div className="muted">
        Start a dev server bound to 0.0.0.0 (e.g. <code>npm run dev -- -H 0.0.0.0</code>) in the task's terminal.
      </div>
      {error && <div className="error">{error}</div>}
    </div>
  )
}

function SidePanel({ task }: { task: TaskSummary }) {
  const openTab = useWorkbench((s) => s.openTab)
  const changes = useTaskChanges(task.id, task.status !== 'stopped' && task.status !== 'preparing')
  const archive = async () => {
    if (!window.confirm('Archive this task? Its workspace is deleted; the transcript is kept.')) return
    await api.archiveTask(task.id)
  }
  return (
    <aside className="task-side">
      <div className="sidebar-section-header">
        <span>Changes</span>
        {changes.data && <span className="count">{changes.data.length}</span>}
      </div>
      {changes.error && <div className="sidebar-note error">{changes.error.message}</div>}
      {changes.data?.length === 0 && <div className="sidebar-note">No changes yet.</div>}
      <ul className="list" aria-label="Task changes">
        {changes.data?.map((c) => (
          <li
            key={c.path}
            className={`list-row change-${c.status}`}
            title={c.path}
            onClick={() => openTab({ id: `tdiff:${task.id}:${c.path}`, kind: 'taskDiff', taskId: task.id, path: c.path })}
          >
            <span className="list-main">{c.path}</span>
            <span className="change-badge">{c.status}</span>
          </li>
        ))}
      </ul>
      {task.status !== 'stopped' && (
        <>
          <div className="sidebar-section-header">
            <span>Pull request</span>
          </div>
          {/* Remounted per round, so the title field starts fresh. */}
          <Publish key={`${task.round}:${task.pr_number}`} task={task} />
          {task.status !== 'preparing' && (
            <>
              <div className="sidebar-section-header">
                <span>Preview</span>
              </div>
              <Preview task={task} />
            </>
          )}
          <div className="task-archive">
            <button className="link-button" onClick={archive}>
              Archive task
            </button>
          </div>
        </>
      )}
    </aside>
  )
}

export function TaskView({ taskId }: { taskId: string }) {
  const task = useTask(taskId)
  const { events, connected } = useTaskEvents(taskId)
  const entries = useMemo(() => buildTranscript(events), [events])
  const bottom = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  useEffect(() => {
    if (stick.current) bottom.current?.scrollIntoView({ block: 'end' })
  }, [entries.length])

  if (task.isLoading) return <div className="editor-message">Loading task…</div>
  if (task.error) return <div className="editor-message error">{task.error.message}</div>
  const t = task.data!
  console.log('[task-debug] render status =', t.status, 'fetching =', task.isFetching, 'updatedAt =', new Date(task.dataUpdatedAt).toISOString())

  return (
    <div className="task-view">
      <div className="task-main">
        <header className="task-header">
          <h1>{t.title}</h1>
          <div className="pr-meta">
            <span className={`task-status status-${t.status}`}>{STATUS_LABEL[t.status] ?? t.status}</span>
            <span>
              {t.provider}
              {t.model ? ` · ${t.model}` : ''}
            </span>
            <span>
              {t.branch_named ? <code>{t.branch}</code> : <span title={t.branch}>new branch</span>} from{' '}
              <code>{t.base_branch}</code>
            </span>
            <span className="muted">{formatCost(t)}</span>
            {t.status !== 'stopped' && t.status !== 'preparing' && (
              <button
                className="button secondary"
                onClick={() => useWorkbench.setState({ terminalTask: t.id })}
                title="A shell in this task's workspace (Ctrl+`)"
              >
                Terminal
              </button>
            )}
            {!connected && t.status !== 'stopped' && <span className="muted">reconnecting…</span>}
          </div>
        </header>
        <div
          className="transcript"
          onScroll={(e) => {
            const el = e.currentTarget
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
          }}
        >
          {entries.map((entry, i) => (
            <EntryView taskId={t.id} key={entry.kind === 'event' ? entry.event.seq : entry.kind === 'tool' ? `t${entry.id}` : `l${i}`} entry={entry} />
          ))}
          {t.status === 'running' && <div className="msg-status muted working">Working…</div>}
          <div ref={bottom} />
        </div>
        <Composer task={t} />
      </div>
      <SidePanel task={t} />
    </div>
  )
}
