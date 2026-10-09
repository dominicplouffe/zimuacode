import { useQuery } from '@tanstack/react-query'
import { api, type Usage } from '../api/client'

type Row = Usage['total']

const tokens = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n))

function Table({ title, rows }: { title: string; rows: Row[] }) {
  return (
    <section className="pr-section">
      <h2>{title}</h2>
      <table className="table">
        <thead>
          <tr>
            <th scope="col"></th>
            <th scope="col">Tasks</th>
            <th scope="col">Input tokens</th>
            <th scope="col">Output tokens</th>
            <th scope="col">Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <th scope="row">{r.key}</th>
              <td>{r.tasks}</td>
              <td>{tokens(r.input_tokens)}</td>
              <td>{tokens(r.output_tokens)}</td>
              <td>{r.cost_usd ? `$${r.cost_usd.toFixed(2)}` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

export function UsageView() {
  const usage = useQuery({ queryKey: ['usage'], queryFn: api.usage })
  if (usage.isLoading) return <div className="editor-message">Loading usage…</div>
  if (usage.error) return <div className="editor-message error">{usage.error.message}</div>
  const u = usage.data!
  return (
    <div className="pr-view">
      <h1>Agent usage</h1>
      <p className="muted">
        {u.total.tasks} tasks · {tokens(u.total.input_tokens + u.total.output_tokens)} tokens
        {u.total.cost_usd ? ` · $${u.total.cost_usd.toFixed(2)} reported` : ''}. Cost is only reported for API keys;
        subscription logins (setup tokens, ChatGPT plans) count against your plan's limits instead.
      </p>
      <Table title="By agent" rows={u.by_provider} />
      <Table title="By repository" rows={u.by_repo} />
    </div>
  )
}
