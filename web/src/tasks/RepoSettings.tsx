import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useWorkbench } from '../state/store'

/** Environment variables and setup script for agent tasks in the current repository. */
export function RepoSettings() {
  const queryClient = useQueryClient()
  const repo = useWorkbench((s) => s.repo)
  const config = useQuery({
    queryKey: ['agentConfig', repo?.owner, repo?.name],
    queryFn: () => api.agentConfig(repo!.owner, repo!.name),
    enabled: repo !== null,
  })
  const [script, setScript] = useState<string | null>(null)
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  if (!repo) return <div className="editor-message">Open a repository first.</div>

  const save = async (body: { env?: Record<string, string | null>; setup_script?: string }) => {
    setError(null)
    setSaved(false)
    try {
      const data = await api.saveAgentConfig(repo.owner, repo.name, body)
      queryClient.setQueryData(['agentConfig', repo.owner, repo.name], data)
      setSaved(true)
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return false
    }
  }

  const currentScript = script ?? config.data?.setup_script ?? ''

  return (
    <div className="pr-view">
      <h1>Agent settings for {repo.owner}/{repo.name}</h1>
      <p className="muted">Used by every agent task in this repository.</p>

      <section className="pr-section" aria-label="Environment variables">
        <h2>Environment variables</h2>
        <p className="muted">
          Available to the setup script, the agent and the terminal. Values are stored encrypted and can't be read back;
          save a variable again to change it.
        </p>
        <ul className="list" aria-label="Variables">
          {config.data?.env_keys.map((key) => (
            <li key={key} className="list-row">
              <code className="list-main">{key}</code>
              <button className="link-button" onClick={() => save({ env: { [key]: null } })}>
                Remove
              </button>
            </li>
          ))}
        </ul>
        <div className="merge-row">
          <input
            className="input"
            aria-label="Variable name"
            placeholder="NAME"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            style={{ maxWidth: 220 }}
          />
          <input
            className="input"
            aria-label="Variable value"
            placeholder="value"
            type="password"
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
          />
          <button
            className="button"
            disabled={!newKey.trim()}
            onClick={async () => {
              if (await save({ env: { [newKey.trim()]: newValue } })) {
                setNewKey('')
                setNewValue('')
              }
            }}
          >
            Add
          </button>
        </div>
      </section>

      <section className="pr-section" aria-label="Setup script">
        <h2>Setup script</h2>
        <p className="muted">
          Runs in the workspace after cloning, before the agent starts, e.g. <code>npm ci</code> or <code>uv sync</code>. It
          stops at the first failing command.
        </p>
        <textarea
          className="input mono"
          rows={8}
          aria-label="Setup script"
          spellCheck={false}
          value={currentScript}
          onChange={(e) => setScript(e.target.value)}
        />
        <div className="form-actions">
          <button
            className="button"
            disabled={script === null || script === config.data?.setup_script}
            onClick={() => save({ setup_script: currentScript })}
          >
            Save script
          </button>
        </div>
      </section>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {saved && !error && <p className="muted">Saved.</p>}
    </div>
  )
}
