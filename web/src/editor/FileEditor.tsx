import Editor from '@monaco-editor/react'
import { useEffectiveSettings, useFile, useTree } from '../api/hooks'
import { useWorkbench } from '../state/store'
import { branchKey, useWorkingCopy } from '../state/workingCopy'
import { editorOptions } from './editorOptions'

export function FileEditor({ path, theme }: { path: string; theme: string }) {
  const repo = useWorkbench((s) => s.repo)
  const settings = useEffectiveSettings()
  const tree = useTree(repo)
  const key = repo ? branchKey(repo) : ''
  const change = useWorkingCopy((s) => s.changes[key]?.[path])
  const edit = useWorkingCopy((s) => s.edit)
  const discard = useWorkingCopy((s) => s.discard)
  const isNew = change?.original === null
  // Read at the tree's commit, so the editor and the explorer show the same snapshot.
  const file = useFile(repo, isNew ? null : path, tree.data?.commit_sha)

  if (change?.content === null) {
    return (
      <div className="editor-message">
        {path} is deleted in your uncommitted changes.{' '}
        <button className="button" onClick={() => discard(key, path)}>
          Restore
        </button>
      </div>
    )
  }
  if (!isNew) {
    if (tree.isLoading || file.isLoading) return <div className="editor-message">Loading {path}…</div>
    if (tree.error || file.error)
      return <div className="editor-message error">{(tree.error ?? file.error)!.message}</div>
    if (!file.data) return null
    if (file.data.binary) return <div className="editor-message">This file is binary and can't be shown.</div>
    if (file.data.too_large) return <div className="editor-message">This file is too large to open.</div>
  }
  const original = isNew ? null : (file.data?.content ?? '')

  return (
    <Editor
      // One model per branch and path; the working copy keeps edits across reloads.
      path={`${key}/${path}`}
      value={change?.content ?? original ?? ''}
      theme={theme}
      onChange={(value) => edit(key, path, original, value ?? '')}
      options={editorOptions(settings)}
    />
  )
}
