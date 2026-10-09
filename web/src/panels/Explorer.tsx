import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, type TreeEntry } from '../api/client'
import { useTree } from '../api/hooks'
import { fileTabId, useWorkbench } from '../state/store'
import { branchKey, changeKind, useWorkingCopy, type ChangeKind } from '../state/workingCopy'
import { buildFileTree, type FileNode } from './fileTree'

interface NodeProps {
  node: FileNode
  depth: number
  expanded: Set<string>
  toggle: (path: string) => void
  kinds: Map<string, ChangeKind>
  onDelete: (path: string) => void
}

function Node({ node, depth, expanded, toggle, kinds, onDelete }: NodeProps) {
  const openFile = useWorkbench((s) => s.openFile)
  const active = useWorkbench((s) => s.activeTab === fileTabId(node.path))
  const isOpen = expanded.has(node.path)
  const kind = kinds.get(node.path)
  return (
    <>
      <div
        role="treeitem"
        aria-expanded={node.isDir ? isOpen : undefined}
        aria-selected={active}
        className={`tree-row${active ? ' selected' : ''}${kind ? ` change-${kind}` : ''}`}
        style={{ paddingLeft: 8 + depth * 12 }}
        title={node.path}
        onClick={() => (node.isDir ? toggle(node.path) : openFile(node.path))}
      >
        <span className="tree-twisty">{node.isDir ? (isOpen ? '▾' : '▸') : ''}</span>
        <span className="tree-name">{node.name}</span>
        {kind && <span className="change-badge">{kind}</span>}
        {!node.isDir && kind !== 'D' && (
          <button
            className="row-action"
            title={`Delete ${node.name}`}
            aria-label={`Delete ${node.name}`}
            onClick={(e) => {
              e.stopPropagation()
              onDelete(node.path)
            }}
          >
            🗑
          </button>
        )}
      </div>
      {node.isDir &&
        isOpen &&
        node.children.map((child) => (
          <Node
            key={child.path}
            node={child}
            depth={depth + 1}
            expanded={expanded}
            toggle={toggle}
            kinds={kinds}
            onDelete={onDelete}
          />
        ))}
    </>
  )
}

export function Explorer() {
  const queryClient = useQueryClient()
  const repo = useWorkbench((s) => s.repo)
  const setPalette = useWorkbench((s) => s.setPalette)
  const tree = useTree(repo)
  const key = repo ? branchKey(repo) : null
  const branchChanges = useWorkingCopy((s) => (key ? s.changes[key] : undefined))
  const remove = useWorkingCopy((s) => s.remove)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)

  const kinds = useMemo(
    () => new Map(Object.values(branchChanges ?? {}).map((c) => [c.path, changeKind(c)])),
    [branchChanges],
  )
  const nodes = useMemo(() => {
    const entries: TreeEntry[] = [...(tree.data?.entries ?? [])]
    for (const [path, kind] of kinds) if (kind === 'A') entries.push({ path, type: 'blob' })
    return buildFileTree(entries)
  }, [tree.data, kinds])

  const toggle = (path: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })

  const onDelete = async (path: string) => {
    if (!repo || !key || !tree.data) return
    setError(null)
    const existing = branchChanges?.[path]
    try {
      // The original is kept so the deletion can be diffed and discarded. A file added
      // locally has none; deleting it just forgets it.
      let original = existing ? (existing.original ?? '') : null
      if (original === null) {
        const commit = tree.data.commit_sha
        const file = await queryClient.fetchQuery({
          queryKey: ['file', repo.owner, repo.name, commit, path],
          queryFn: () => api.file(repo.owner, repo.name, path, commit),
          staleTime: Infinity,
        })
        original = file.content ?? ''
      }
      remove(key, path, original)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

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
        <span>{repo.name}</span>
        <button className="header-action" title="New File…" aria-label="New File" onClick={() => setPalette('newFile')}>
          +
        </button>
      </div>
      {tree.isLoading && <div className="sidebar-note">Loading…</div>}
      {tree.error && <div className="sidebar-note error">{tree.error.message}</div>}
      {error && <div className="sidebar-note error">{error}</div>}
      {tree.data?.truncated && (
        <div className="sidebar-note">This repository is too large to list completely.</div>
      )}
      <div role="tree" aria-label="Files" className="tree">
        {nodes.map((node) => (
          <Node
            key={node.path}
            node={node}
            depth={0}
            expanded={expanded}
            toggle={toggle}
            kinds={kinds}
            onDelete={onDelete}
          />
        ))}
      </div>
    </div>
  )
}
