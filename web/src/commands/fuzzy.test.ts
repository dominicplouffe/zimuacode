import { describe, expect, it } from 'vitest'
import { fuzzyFilter, fuzzyScore } from './fuzzy'

describe('fuzzy', () => {
  it('matches subsequences case-insensitively', () => {
    expect(fuzzyScore('apy', 'src/App.py')).not.toBeNull()
    expect(fuzzyScore('xyz', 'src/App.py')).toBeNull()
  })

  it('ranks file-name matches above directory matches', () => {
    const files = ['main/other.ts', 'lib/main.ts']
    expect(fuzzyFilter(files, 'main', (f) => f)[0]).toBe('lib/main.ts')
  })

  it('ranks consecutive matches higher', () => {
    const files = ['s/e/t/t/i/n/g/s.py', 'settings.py']
    expect(fuzzyFilter(files, 'settings', (f) => f)[0]).toBe('settings.py')
  })

  it('returns everything up to the limit for an empty query', () => {
    expect(fuzzyFilter(['a', 'b', 'c'], '', (f) => f, 2)).toEqual(['a', 'b'])
  })
})
