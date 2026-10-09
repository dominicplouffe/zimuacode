import { useMemo, useState } from 'react'
import { useTree } from '../api/hooks'
import { fileTabId, useWorkbench } from '../state/store'
import { buildFileTree, type FileNode } from './fileTree'

function Node({
  node,
  depth,
  expanded,
  toggle,
}: {
  node: FileNode
  depth: number
  expanded: Set<string>
  toggle: (path: string) => void
}) {
  const openFile = useWorkbench((s) => s.openFile)
  const active = useWorkbench((s) => s.activeTab === fileTabId(node.path))
  const isOpen = expanded.has(node.path)
  return (
    <>
      <div
        role="treeitem"
        aria-expanded={node.isDir ? isOpen : undefined}
        aria-selected={active}
        className={`tree-row${active ? ' selected' : ''}`}
        style={{ paddingLeft: 8 + depth * 12 }}
        title={node.path}
        onClick={() => (node.isDir ? toggle(node.path) : openFile(node.path))}
      >
        <span className="tree-twisty">{node.isDir ? (isOpen ? '▾' : '▸') : ''}</span>
        <span className="tree-name">{node.name}</span>
      </div>
      {node.isDir &&
        isOpen &&
        node.children.map((child) => (
          <Node key={child.path} node={child} depth={depth + 1} expanded={expanded} toggle={toggle} />
        ))}
    </>
  )
}

export function Explorer() {
  const repo = useWorkbench((s) => s.repo)
  const setPalette = useWorkbench((s) => s.setPalette)
  const tree = useTree(repo)
  const nodes = useMemo(() => buildFileTree(tree.data?.entries ?? []), [tree.data])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggle = (path: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })

  if (!repo) {
    return (
      <div className="sidebar-empty">
        <p>No repository open.</p>
        <button className="button" onClick={() => setPalette('repos')}>
          Open Repository
        </button>
      </div>
    )
  }

  return (
    <div className="explorer">
      <div className="sidebar-section-header" title={`${repo.owner}/${repo.name}`}>
        {repo.name}
      </div>
      {tree.isLoading && <div className="sidebar-note">Loading…</div>}
      {tree.error && <div className="sidebar-note error">{tree.error.message}</div>}
      {tree.data?.truncated && (
        <div className="sidebar-note">This repository is too large to list completely.</div>
      )}
      <div role="tree" aria-label="Files" className="tree">
        {nodes.map((node) => (
          <Node key={node.path} node={node} depth={0} expanded={expanded} toggle={toggle} />
        ))}
      </div>
    </div>
  )
}
