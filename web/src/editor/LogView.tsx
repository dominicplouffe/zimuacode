import Editor, { type OnMount } from '@monaco-editor/react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useEffectiveSettings } from '../api/hooks'
import { useWorkbench } from '../state/store'
import { cleanLog } from './cleanLog'
import { editorOptions } from './editorOptions'

export function LogView({ jobId, theme }: { jobId: number; theme: string }) {
  const repo = useWorkbench((s) => s.repo)
  const settings = useEffectiveSettings()
  const log = useQuery({
    queryKey: ['logs', repo?.owner, repo?.name, jobId],
    queryFn: async () => cleanLog(await api.checkLogs(repo!.owner, repo!.name, jobId)),
    enabled: repo !== null,
  })

  // Failures are at the end of a log, so start there.
  const onMount: OnMount = (editor) => {
    const lines = editor.getModel()?.getLineCount() ?? 1
    editor.revealLine(lines)
    editor.setPosition({ lineNumber: lines, column: 1 })
  }

  if (log.isLoading) return <div className="editor-message">Loading log…</div>
  if (log.error) return <div className="editor-message error">{log.error.message}</div>
  return (
    <Editor
      path={`log:${jobId}`}
      language="plaintext"
      value={log.data ?? ''}
      theme={theme}
      onMount={onMount}
      options={{ ...editorOptions(settings), readOnly: true, wordWrap: 'on' }}
    />
  )
}
