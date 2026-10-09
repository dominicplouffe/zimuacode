import { DiffEditor } from '@monaco-editor/react'
import { useEffectiveSettings, useTaskFile } from '../api/hooks'
import { editorOptions } from '../editor/editorOptions'

/** A file in a task's workspace against the commit the task started from. Live: it
 * refreshes as the agent edits. */
export function TaskDiffView({ taskId, path, theme }: { taskId: string; path: string; theme: string }) {
  const settings = useEffectiveSettings()
  const base = useTaskFile(taskId, path, 'base')
  const working = useTaskFile(taskId, path, 'working')
  if (base.isLoading || working.isLoading) return <div className="editor-message">Loading diff…</div>
  const error = base.error ?? working.error
  if (error) return <div className="editor-message error">{error.message}</div>
  if (base.data?.binary || working.data?.binary) return <div className="editor-message">Binary file changed.</div>
  if (base.data?.too_large || working.data?.too_large)
    return <div className="editor-message">This file is too large to diff.</div>
  return (
    <DiffEditor
      original={base.data?.content ?? ''}
      modified={working.data?.content ?? ''}
      originalModelPath={`task:${taskId}:base:${path}`}
      modifiedModelPath={`task:${taskId}:working:${path}`}
      theme={theme}
      options={{ ...editorOptions(settings), readOnly: true, originalEditable: false }}
    />
  )
}
