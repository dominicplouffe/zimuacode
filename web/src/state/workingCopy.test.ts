import { beforeEach, describe, expect, it } from 'vitest'
import { changeKind, useWorkingCopy } from './workingCopy'

const key = 'octo/app@main'
const changes = () => useWorkingCopy.getState().changes[key] ?? {}

describe('working copy', () => {
  beforeEach(() => useWorkingCopy.setState({ changes: {} }))

  it('tracks edits and drops them when reverted', () => {
    const wc = useWorkingCopy.getState()
    wc.edit(key, 'a.py', 'x = 1\n', 'x = 2\n')
    expect(changeKind(changes()['a.py'])).toBe('M')
    // A later edit keeps the first original.
    wc.edit(key, 'a.py', 'x = 2\n', 'x = 1\n')
    expect(changes()['a.py']).toBeUndefined()
    expect(useWorkingCopy.getState().changes[key]).toBeUndefined()
  })

  it('creates and deletes files', () => {
    const wc = useWorkingCopy.getState()
    wc.create(key, 'new.ts')
    expect(changeKind(changes()['new.ts'])).toBe('A')
    wc.edit(key, 'new.ts', null, 'export {}\n')
    expect(changes()['new.ts']).toEqual({ path: 'new.ts', original: null, content: 'export {}\n' })
    wc.remove(key, 'new.ts', '')
    expect(changes()['new.ts']).toBeUndefined()

    wc.edit(key, 'b.py', 'old\n', 'edited\n')
    wc.remove(key, 'b.py', 'edited\n')
    expect(changes()['b.py']).toEqual({ path: 'b.py', original: 'old\n', content: null })
    expect(changeKind(changes()['b.py'])).toBe('D')
  })

  it('keeps branches separate and persists', () => {
    const wc = useWorkingCopy.getState()
    wc.edit(key, 'a.py', '1', '2')
    wc.edit('octo/app@dev', 'a.py', '1', '3')
    wc.clear(key)
    expect(useWorkingCopy.getState().changes).toEqual({
      'octo/app@dev': { 'a.py': { path: 'a.py', original: '1', content: '3' } },
    })
    expect(JSON.parse(localStorage.getItem('zimua.workingCopy')!)).toEqual(useWorkingCopy.getState().changes)
  })
})
