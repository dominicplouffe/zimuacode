import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { disablePush, enablePush, pushState, type PushState } from './notifications'
import { api, type Provider } from '../api/client'
import { useProviders } from '../api/hooks'

/** One login, used by one or more providers (Codex and Codex Cloud share theirs). */
function ProviderAccount({ providers }: { providers: Provider[] }) {
  const provider = providers[0]
  const names = providers.map((p) => p.name).join(' · ')
  const queryClient = useQueryClient()
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['providers'] })

  const save = async () => {
    setError(null)
    try {
      await api.setCredential(provider.credential_key, value)
      setValue('')
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <section className="pr-section" aria-label={provider.name}>
      <h2>
        {names}{' '}
        <span className={`task-status ${provider.configured ? 'status-idle' : 'status-stopped'}`}>
          {provider.configured ? 'Signed in' : 'Not signed in'}
        </span>
      </h2>
      {providers.map((p) => (
        <p key={p.id} className="muted">
          {providers.length > 1 && <strong>{p.name}: </strong>}
          {p.experimental && <span className="tag">experimental</span>} {p.credential_help}
        </p>
      ))}
      <div className="merge-row">
        <textarea
          className="input"
          rows={1}
          aria-label={`${provider.name} credential`}
          placeholder={provider.configured ? 'Paste a new value to replace the saved one' : 'Paste here'}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          spellCheck={false}
        />
        <button className="button" disabled={!value.trim()} onClick={save}>
          Save
        </button>
        {provider.configured && (
          <button
            className="button secondary"
            onClick={async () => {
              await api.deleteCredential(provider.credential_key)
              refresh()
            }}
          >
            Remove
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  )
}

function Notifications() {
  const [state, setState] = useState<PushState | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    pushState().then(setState, () => setState('unsupported'))
  }, [])
  const run = async (action: () => Promise<PushState>) => {
    setError(null)
    try {
      setState(await action())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }
  return (
    <section className="pr-section" aria-label="Notifications">
      <h2>Notifications on this device</h2>
      <p className="muted">
        Get a notification when an agent finishes or fails, or CI fails on a pull request an agent opened, even with the IDE
        closed. Turn them off everywhere with <code>notifications.enabled</code> in settings.json.
      </p>
      {state === 'unsupported' && (
        <p className="muted">This browser can't receive push notifications (the desktop app can't either, yet).</p>
      )}
      {state === 'denied' && <p className="muted">Notifications are blocked for this site in your browser settings.</p>}
      <div className="merge-row">
        {state === 'off' && (
          <button className="button" onClick={() => run(enablePush)}>
            Enable notifications
          </button>
        )}
        {state === 'on' && (
          <>
            <span className="task-status status-idle">On</span>
            <button className="button secondary" onClick={() => run(async () => (await api.testPush(), 'on'))}>
              Send a test
            </button>
            <button className="button secondary" onClick={() => run(disablePush)}>
              Turn off
            </button>
          </>
        )}
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  )
}

export function Accounts() {
  const providers = useProviders()
  const groups: Provider[][] = []
  for (const p of providers.data ?? []) {
    const group = groups.find((g) => g[0].credential_key === p.credential_key)
    if (group) group.push(p)
    else groups.push([p])
  }
  return (
    <div className="pr-view">
      <h1>Agent accounts</h1>
      <p className="muted">
        Credentials are stored encrypted on your server and passed only to the agent CLI when a task runs. They never come
        back to the browser.
      </p>
      {providers.error && <p className="error">{providers.error.message}</p>}
      {groups.map((group) => (
        <ProviderAccount key={group[0].credential_key} providers={group} />
      ))}
      <Notifications />
    </div>
  )
}
