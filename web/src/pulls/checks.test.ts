import { describe, expect, it } from 'vitest'
import type { Check } from '../api/client'
import { checkState, overallState } from './Checks'

const check = (status: string, conclusion: string | null): Check => ({
  id: 1,
  name: 'x',
  kind: 'check_run',
  status,
  conclusion,
  url: null,
  has_logs: false,
})

describe('check states', () => {
  it('classifies single checks', () => {
    expect(checkState(check('queued', null))).toBe('pending')
    expect(checkState(check('completed', 'success'))).toBe('success')
    expect(checkState(check('completed', 'skipped'))).toBe('neutral')
    expect(checkState(check('completed', 'timed_out'))).toBe('failure')
  })

  it('rolls up: failure, then pending, then success', () => {
    expect(overallState([])).toBeNull()
    expect(overallState([check('completed', 'success'), check('in_progress', null)])).toBe('pending')
    expect(overallState([check('in_progress', null), check('completed', 'failure')])).toBe('failure')
    expect(overallState([check('completed', 'success'), check('completed', 'skipped')])).toBe('success')
  })
})
