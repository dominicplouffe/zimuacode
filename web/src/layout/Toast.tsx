import { useWorkbench } from '../state/store'

export function Toast() {
  const toast = useWorkbench((s) => s.toast)
  if (!toast) return null
  return (
    <div className={`toast${toast.error ? ' error' : ''}`} role={toast.error ? 'alert' : 'status'}>
      {toast.message}
      <button className="tab-close" aria-label="Dismiss" onClick={() => useWorkbench.setState({ toast: null })}>
        ×
      </button>
    </div>
  )
}
