import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, type TaskEvent, type TaskSummary } from '../api/client'
import { useTask, useTaskChanges } from '../api/hooks'
import { useWorkbench } from '../state/store'
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

function EventView({ event }: { event: TaskEvent }) {
  switch (event.type) {
    case 'user_message':
      return (
        <div className="msg msg-user">
          {event.data.queued ? <div className="msg-note">Queued until the agent finishes</div> : null}
          <div className="msg-text">{text(event)}</div>
        </div>
      )
    case 'assistant_text':
      return (
        <div className={`msg msg-assistant markdown${event.data.subagent ? ' subagent' : ''}`}>
          <Markdown remarkPlugins={[remarkGfm]}>{text(event)}</Markdown>
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

function EntryView({ entry }: { entry: Entry }) {
  if (entry.kind === 'event') return <EventView event={entry.event} />
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
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const working = task.status === 'running' || task.status === 'preparing'
  const canSend = draft.trim() !== '' && task.status !== 'stopped'

  const send = async () => {
    setError(null)
    try {
      await api.sendMessage(task.id, draft.trim())
      setDraft('')
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
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && canSend) send()
        }}
      />
      <div className="form-actions">
        {error && <span className="error">{error}</span>}
        {task.status === 'running' && (
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

function Publish({ task }: { task: TaskSummary }) {
  const queryClient = useQueryClient()
  const openTab = useWorkbench((s) => s.openTab)
  const [title, setTitle] = useState(task.title)
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
      queryClient.invalidateQueries({ queryKey: ['task', task.id] })
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
      {task.pr_number ? (
        <>
          <button className="link-button" onClick={() => openTab({ id: `pr:${task.pr_number}`, kind: 'pr', number: task.pr_number! })}>
            View PR #{task.pr_number}
          </button>
          <button className="button full" disabled={busy || working} onClick={publish}>
            {busy ? 'Pushing…' : 'Push changes to PR'}
          </button>
        </>
      ) : (
        <>
          <input className="input" aria-label="Pull request title" value={title} onChange={(e) => setTitle(e.target.value)} />
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
          <Publish task={task} />
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
              <code>{t.branch}</code> from <code>{t.base_branch}</code>
            </span>
            <span className="muted">{formatCost(t)}</span>
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
            <EntryView key={entry.kind === 'event' ? entry.event.seq : entry.kind === 'tool' ? `t${entry.id}` : `l${i}`} entry={entry} />
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
