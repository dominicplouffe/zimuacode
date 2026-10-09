import type { TreeEntry } from '../api/client'

export interface FileNode {
  name: string
  path: string
  isDir: boolean
  children: FileNode[]
}

/** Turns GitHub's flat recursive tree into nested nodes, folders first, then by name. */
export function buildFileTree(entries: TreeEntry[]): FileNode[] {
  const root: FileNode = { name: '', path: '', isDir: true, children: [] }
  const dirs = new Map<string, FileNode>([['', root]])

  const dirFor = (path: string): FileNode => {
    const existing = dirs.get(path)
    if (existing) return existing
    const slash = path.lastIndexOf('/')
    const parent = dirFor(slash < 0 ? '' : path.slice(0, slash))
    const node: FileNode = { name: path.slice(slash + 1), path, isDir: true, children: [] }
    parent.children.push(node)
    dirs.set(path, node)
    return node
  }

  for (const entry of entries) {
    if (entry.type === 'tree') {
      dirFor(entry.path)
    } else if (entry.type === 'blob') {
      const slash = entry.path.lastIndexOf('/')
      dirFor(slash < 0 ? '' : entry.path.slice(0, slash)).children.push({
        name: entry.path.slice(slash + 1),
        path: entry.path,
        isDir: false,
        children: [],
      })
    }
  }

  const sort = (node: FileNode) => {
    node.children.sort((a, b) =>
      a.isDir === b.isDir ? a.name.localeCompare(b.name) : a.isDir ? -1 : 1,
    )
    node.children.forEach(sort)
  }
  sort(root)
  return root.children
}
