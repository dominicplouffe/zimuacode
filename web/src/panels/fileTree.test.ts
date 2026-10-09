import { describe, expect, it } from 'vitest'
import { buildFileTree } from './fileTree'

describe('buildFileTree', () => {
  it('nests entries with folders first', () => {
    const tree = buildFileTree([
      { path: 'README.md', type: 'blob' },
      { path: 'src', type: 'tree' },
      { path: 'src/b.py', type: 'blob' },
      { path: 'src/a.py', type: 'blob' },
      { path: 'src/lib', type: 'tree' },
      { path: 'src/lib/x.ts', type: 'blob' },
      { path: 'vendor', type: 'commit' },
    ])
    expect(tree.map((n) => n.name)).toEqual(['src', 'README.md'])
    expect(tree[0].children.map((n) => n.name)).toEqual(['lib', 'a.py', 'b.py'])
    expect(tree[0].children[0].children[0].path).toBe('src/lib/x.ts')
  })

  it('creates missing parent folders when the tree was truncated', () => {
    const tree = buildFileTree([{ path: 'a/b/c.txt', type: 'blob' }])
    expect(tree[0].path).toBe('a')
    expect(tree[0].children[0].path).toBe('a/b')
  })
})
