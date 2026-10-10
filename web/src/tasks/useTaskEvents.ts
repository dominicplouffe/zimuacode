import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import type { TaskEvent } from '../api/client'

/**
 * The live transcript of a task over server-sent events. EventSource reconnects on its own
 * and resumes from the last event it saw, so a laptop waking from sleep catches up.
 */
export function useTaskEvents(taskId: string): { events: TaskEvent[]; connected: boolean } {
  const queryClient = useQueryClient()
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [connected, setConnected] = useState(false)
  const refreshTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    setEvents([])
    const source = new EventSource(`/api/tasks/${taskId}/events`)
    const refresh = () => {
      clearTimeout(refreshTimer.current)
      refreshTimer.current = setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['task', taskId] })
        queryClient.invalidateQueries({ queryKey: ['tasks'] })
        queryClient.invalidateQueries({ queryKey: ['taskChanges', taskId] })
        queryClient.invalidateQueries({ queryKey: ['taskFile', taskId] })
      }, 300)
    }
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as TaskEvent
      setEvents((prev) => (prev.length && prev[prev.length - 1].seq >= event.seq ? prev : [...prev, event]))
      // Status changes and finished tool calls can change the task and its files.
      if (['status', 'tool_result', 'command', 'file_change', 'usage', 'pr', 'round', 'user_message'].includes(event.type))
        refresh()
    }
    return () => {
      source.close()
      clearTimeout(refreshTimer.current)
    }
  }, [taskId, queryClient])

  return { events, connected }
}
