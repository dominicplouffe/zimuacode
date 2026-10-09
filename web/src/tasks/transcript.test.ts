import { describe, expect, it } from 'vitest'
import type { TaskEvent } from '../api/client'
import { buildTranscript, summarizeTool } from './transcript'

let seq = 0
const ev = (type: string, data: Record<string, unknown> = {}): TaskEvent => ({
  seq: ++seq,
  type,
  data,
  created_at: '2026-10-01T00:00:00Z',
})

describe('summarizeTool', () => {
  it('picks the most telling argument', () => {
    expect(summarizeTool('Bash', { command: 'npm test\nmore', description: 'Run tests' })).toBe('Bash: npm test')
    expect(summarizeTool('Edit', { file_path: 'src/a.ts', old_string: 'x' })).toBe('Edit: src/a.ts')
    expect(summarizeTool('Grep', { pattern: 'TODO' })).toBe('Grep: TODO')
    expect(summarizeTool('TodoWrite', { todos: [] })).toBe('TodoWrite')
    expect(summarizeTool('Mystery', { thing: 'value' })).toBe('Mystery: value')
    expect(summarizeTool('Bash', { command: 'x'.repeat(200) })).toHaveLength(126)
  })
})

describe('buildTranscript', () => {
  it('pairs tool calls with results and groups logs', () => {
    const call = ev('tool_call', { id: 't1', name: 'Bash', input: { command: 'ls' } })
    const result = ev('tool_result', { id: 't1', output: 'a' })
    const entries = buildTranscript([
      ev('user_message', { text: 'hi' }),
      ev('log', { text: 'warn 1' }),
      ev('log', { text: 'warn 2' }),
      call,
      ev('assistant_text', { text: 'working' }),
      result,
      ev('usage', { cost_usd: 1 }),
      ev('tool_result', { id: 'orphan', output: 'b' }),
    ])
    expect(entries.map((e) => e.kind)).toEqual(['event', 'logs', 'tool', 'event', 'event'])
    expect(entries[1]).toMatchObject({ kind: 'logs', events: [{ data: { text: 'warn 1' } }, { data: { text: 'warn 2' } }] })
    expect(entries[2]).toEqual({ kind: 'tool', id: 't1', call, result })
  })
})
