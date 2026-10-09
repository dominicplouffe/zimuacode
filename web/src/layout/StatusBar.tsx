import { useMe } from '../api/hooks'
import { useWorkbench } from '../state/store'

export function StatusBar() {
  const { repo, setPalette } = useWorkbench()
  const me = useMe()
  return (
    <footer className="status-bar">
      {repo ? (
        <>
          <button className="status-item" title="Open another repository" onClick={() => setPalette('repos')}>
            {repo.owner}/{repo.name}
          </button>
          <button className="status-item" title="Switch branch" onClick={() => setPalette('branches')}>
            ⎇ {repo.ref}
          </button>
        </>
      ) : (
        <button className="status-item" onClick={() => setPalette('repos')}>
          Open Repository
        </button>
      )}
      <div className="status-spacer" />
      {me.data && <span className="status-item">{me.data.login}</span>}
    </footer>
  )
}
