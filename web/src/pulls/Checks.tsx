import type { Check } from '../api/client'
import { useWorkbench } from '../state/store'

export type CheckState = 'success' | 'failure' | 'pending' | 'neutral'

export function checkState(c: Check): CheckState {
  if (c.status !== 'completed') return 'pending'
  if (c.conclusion === 'success') return 'success'
  if (c.conclusion === 'neutral' || c.conclusion === 'skipped') return 'neutral'
  return 'failure'
}

/** Overall state: any failure wins, then anything still running. */
export function overallState(checks: Check[]): CheckState | null {
  if (checks.length === 0) return null
  const states = checks.map(checkState)
  if (states.includes('failure')) return 'failure'
  if (states.includes('pending')) return 'pending'
  if (states.includes('success')) return 'success'
  return 'neutral'
}

export const STATE_ICON: Record<CheckState, string> = {
  success: '✓',
  failure: '✗',
  pending: '●',
  neutral: '–',
}

/** Opens a GitHub Actions log in a tab; other CI systems open their own page. */
export function openCheck(check: Check) {
  if (check.has_logs) {
    useWorkbench.getState().openTab({ id: `log:${check.id}`, kind: 'log', jobId: check.id, title: check.name })
  } else if (check.url) {
    window.open(check.url, '_blank', 'noopener')
  }
}

export function ChecksList({ checks }: { checks: Check[] }) {
  if (checks.length === 0) return <p className="muted">No checks reported.</p>
  return (
    <ul className="checks" aria-label="Checks">
      {checks.map((c) => {
        const state = checkState(c)
        const clickable = c.has_logs || c.url
        return (
          <li key={`${c.kind}:${c.id}`} className={`check check-${state}`}>
            <span className="check-icon" aria-label={state}>
              {STATE_ICON[state]}
            </span>
            {clickable ? (
              <button className="link-button" onClick={() => openCheck(c)} title={c.has_logs ? 'Show log' : 'Open details'}>
                {c.name}
              </button>
            ) : (
              <span>{c.name}</span>
            )}
            <span className="muted">{c.conclusion ?? c.status.replace('_', ' ')}</span>
          </li>
        )
      })}
    </ul>
  )
}
