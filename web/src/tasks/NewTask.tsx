import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useBranches, useEffectiveSettings, useProviders } from '../api/hooks'
import { useWorkbench } from '../state/store'
import { ImageStrip, usePastedImages } from './images'

export function NewTask() {
  const queryClient = useQueryClient()
  const { repo, openTab, closeTab, setPalette } = useWorkbench()
  const settings = useEffectiveSettings()
  const providers = useProviders()
  const branches = useBranches(repo)
  const [provider, setProvider] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(null)
  // A draft (e.g. from "Fix with agent") prefills the form once.
  const [draft] = useState(() => {
    const d = useWorkbench.getState().newTaskDraft
    useWorkbench.setState({ newTaskDraft: null })
    return d
  })
  const [base, setBase] = useState(draft?.baseBranch ?? repo?.ref ?? '')
  const [prompt, setPrompt] = useState(draft?.prompt ?? '')
  const prNumber = draft?.prNumber ?? null
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const preferred = provider ?? (settings?.['ai.defaultProvider'] as string | undefined) ?? 'claude-code'
  // A default naming a removed agent falls back to Claude Code.
  const chosen =
    providers.data && !providers.data.some((p) => p.id === preferred) ? 'claude-code' : preferred
  const info = providers.data?.find((p) => p.id === chosen)
  const pasted = usePastedImages(info?.capabilities.images ?? true)

  if (!repo) {
    return (
      <div className="editor-message">
        Open a repository first.{' '}
        <button className="button" onClick={() => setPalette('repos')}>
          Open Repository
        </button>
      </div>
    )
  }

  const chosenModel = model ?? (settings?.['ai.defaultModel'] as string | undefined) ?? ''

  const start = async () => {
    setBusy(true)
    setError(null)
    try {
      const task = await api.createTask({
        provider: chosen,
        owner: repo.owner,
        name: repo.name,
        base_branch: base,
        prompt: prompt.trim(),
        model: chosenModel.trim() || null,
        pr_number: prNumber,
        images: pasted.images.map((i) => i.data),
      })
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      closeTab('newTask')
      openTab({ id: `task:${task.id}`, kind: 'task', taskId: task.id })
      useWorkbench.setState({ sidebar: 'tasks', sidebarVisible: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="pr-view">
      <h1>New agent task</h1>
      <p className="muted">
        The agent works on its own branch of <strong>{repo.owner}/{repo.name}</strong> on your server, and keeps going if you
        close this window.
      </p>
      <label className="form-field">
        What should the agent do?
        <textarea
          className="input"
          rows={8}
          autoFocus
          aria-label="Task prompt"
          placeholder="e.g. Add a dark mode toggle to the settings page, with tests"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onPaste={pasted.onPaste}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && prompt.trim() && !busy) start()
          }}
        />
      </label>
      <ImageStrip images={pasted.images} onRemove={pasted.remove} />
      <div className="form-row">
        <label>
          Agent
          <select className="input" aria-label="Agent" value={chosen} onChange={(e) => setProvider(e.target.value)}>
            {providers.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.experimental ? ' — experimental' : ''}
                {p.configured ? '' : ' (not signed in)'}
              </option>
            ))}
          </select>
        </label>
        <label>
          Model
          <input
            className="input"
            aria-label="Model"
            placeholder="Provider default"
            value={chosenModel}
            onChange={(e) => setModel(e.target.value)}
          />
        </label>
        <label>
          {prNumber ? 'Works on' : 'Start from'}
          <select
            className="input"
            aria-label="Base branch"
            value={base}
            disabled={prNumber !== null}
            onChange={(e) => setBase(e.target.value)}
          >
            {(branches.data ?? [{ name: base }]).map((b) => (
              <option key={b.name}>{b.name}</option>
            ))}
          </select>
        </label>
      </div>
      {prNumber !== null && (
        <p className="muted">
          The agent works directly on <code>{base}</code>, so publishing pushes to PR #{prNumber}.
        </p>
      )}
      {info?.capabilities.runs_on === 'vendor' && (
        <p className="muted">
          {info.name} runs the task on the vendor's own servers. You get a link to follow it there; the transcript doesn't
          stream here. {info.credential_help}
        </p>
      )}
      {info && !info.configured && (
        <p className="muted">
          {info.name} isn't signed in, so the task will likely fail.{' '}
          <button className="link-button" onClick={() => openTab({ id: 'accounts', kind: 'accounts' })}>
            Set up agent accounts
          </button>
        </p>
      )}
      <div className="form-actions">
        {(error ?? pasted.error) && <span className="error">{error ?? pasted.error}</span>}
        <button className="button" disabled={busy || !prompt.trim() || !base} onClick={start}>
          {busy ? 'Starting…' : 'Start task'}
        </button>
      </div>
    </div>
  )
}
