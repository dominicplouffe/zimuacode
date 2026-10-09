import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Provider } from '../api/client'
import { useProviders } from '../api/hooks'

function ProviderAccount({ provider }: { provider: Provider }) {
  const queryClient = useQueryClient()
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['providers'] })

  const save = async () => {
    setError(null)
    try {
      await api.setCredential(provider.id, value)
      setValue('')
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <section className="pr-section" aria-label={provider.name}>
      <h2>
        {provider.name}{' '}
        <span className={`task-status ${provider.configured ? 'status-idle' : 'status-stopped'}`}>
          {provider.configured ? 'Signed in' : 'Not signed in'}
        </span>
      </h2>
      <p className="muted">{provider.credential_help}</p>
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
              await api.deleteCredential(provider.id)
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

export function Accounts() {
  const providers = useProviders()
  return (
    <div className="pr-view">
      <h1>Agent accounts</h1>
      <p className="muted">
        Credentials are stored encrypted on your server and passed only to the agent CLI when a task runs. They never come
        back to the browser.
      </p>
      {providers.error && <p className="error">{providers.error.message}</p>}
      {providers.data?.map((p) => <ProviderAccount key={p.id} provider={p} />)}
    </div>
  )
}
