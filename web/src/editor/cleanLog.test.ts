import { describe, expect, it } from 'vitest'
import { cleanLog } from './cleanLog'

describe('cleanLog', () => {
  it('strips timestamps and color codes and labels markers', () => {
    const raw =
      '\uFEFF2026-10-01T00:00:01.0000000Z ##[group]Run npm test\r\n' +
      '2026-10-01T00:00:02.1Z \x1b[31mFAIL\x1b[0m app/page.test.tsx\n' +
      '2026-10-01T00:00:03Z ##[endgroup]\n' +
      '2026-10-01T00:00:04Z ##[error]Process completed with exit code 1.'
    expect(cleanLog(raw)).toBe(
      '▸ Run npm test\nFAIL app/page.test.tsx\n\nERROR: Process completed with exit code 1.',
    )
  })

  it('leaves ordinary text alone', () => {
    expect(cleanLog('hello\nworld')).toBe('hello\nworld')
  })
})
