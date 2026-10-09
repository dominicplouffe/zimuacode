import type { TaskEvent } from '../api/client'

/** A one-line description of a tool call, e.g. "Bash: npm test" or "Edit: src/app.ts". */
export function summarizeTool(name: string, input: unknown): string {
  const args = (input && typeof input === 'object' ? input : {}) as Record<string, unknown>
  const pick = (...keys: string[]) => {
    for (const key of keys) if (typeof args[key] === 'string' && args[key]) return args[key] as string
    return undefined
  }
  const detail =
    pick('command', 'file_path', 'notebook_path', 'path', 'pattern', 'url', 'query', 'description', 'prompt') ??
    Object.values(args).find((v): v is string => typeof v === 'string')
  const oneLine = detail?.split('\n')[0]
  return oneLine ? `${name}: ${oneLine.length > 120 ? oneLine.slice(0, 119) + '…' : oneLine}` : name
}

export type Entry =
  | { kind: 'event'; event: TaskEvent }
  | { kind: 'tool'; id: string; call: TaskEvent; result?: TaskEvent }
  | { kind: 'logs'; events: TaskEvent[] }

/**
 * Groups raw events for display: each tool call with its result, consecutive CLI log lines
 * together. Usage events are left out (they're summarized in the header).
 */
export function buildTranscript(events: TaskEvent[]): Entry[] {
  const entries: Entry[] = []
  const tools = new Map<string, Extract<Entry, { kind: 'tool' }>>()
  for (const event of events) {
    if (event.type === 'usage') continue
    if (event.type === 'tool_call') {
      const id = String(event.data.id ?? event.seq)
      const entry = { kind: 'tool' as const, id, call: event }
      tools.set(id, entry)
      entries.push(entry)
      continue
    }
    if (event.type === 'tool_result') {
      const entry = tools.get(String(event.data.id))
      if (entry) {
        entry.result = event
        continue
      }
    }
    if (event.type === 'log') {
      const last = entries[entries.length - 1]
      if (last?.kind === 'logs') last.events.push(event)
      else entries.push({ kind: 'logs', events: [event] })
      continue
    }
    entries.push({ kind: 'event', event })
  }
  return entries
}
