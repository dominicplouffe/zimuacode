import Editor from '@monaco-editor/react'
import { useEffectiveSettings, useFile } from '../api/hooks'
import { useWorkbench } from '../state/store'
import { editorOptions } from './editorOptions'

export function FileEditor({ path, theme }: { path: string; theme: string }) {
  const repo = useWorkbench((s) => s.repo)
  const settings = useEffectiveSettings()
  const file = useFile(repo, path)

  if (file.isLoading) return <div className="editor-message">Loading {path}…</div>
  if (file.error) return <div className="editor-message error">{file.error.message}</div>
  if (!file.data) return null
  if (file.data.binary) return <div className="editor-message">This file is binary and can't be shown.</div>
  if (file.data.too_large) return <div className="editor-message">This file is too large to open.</div>

  return (
    <Editor
      // One model per repo, ref and path, so switching branches shows the right contents.
      path={`${repo?.owner}/${repo?.name}@${repo?.ref}/${path}`}
      value={file.data.content ?? ''}
      theme={theme}
      options={{ ...editorOptions(settings), readOnly: true }}
    />
  )
}
