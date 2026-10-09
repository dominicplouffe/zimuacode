import { useBranchPull, useChecks, useMe, useTree } from '../api/hooks'
import { overallState, STATE_ICON } from '../pulls/Checks'
import { useWorkbench } from '../state/store'

export function StatusBar() {
  const { repo, setPalette, openTab } = useWorkbench()
  const me = useMe()
  const tree = useTree(repo)
  const pull = useBranchPull(repo)
  const checks = useChecks(repo, tree.data?.commit_sha)
  const ci = checks.data ? overallState(checks.data) : null

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
          {ci && (
            <button
              className={`status-item ci-${ci}`}
              title="Checks on this branch"
              aria-label={`Checks: ${ci}`}
              onClick={() => setPalette('checks')}
            >
              {STATE_ICON[ci]} CI
            </button>
          )}
          {pull.data && (
            <button
              className="status-item"
              title={pull.data.title}
              onClick={() => openTab({ id: `pr:${pull.data!.number}`, kind: 'pr', number: pull.data!.number })}
            >
              PR #{pull.data.number}
            </button>
          )}
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
