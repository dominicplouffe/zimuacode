import { DiffEditor } from '@monaco-editor/react'
import { useEffectiveSettings, useFile } from '../api/hooks'
import { useWorkbench, type DiffSide } from '../state/store'
import { branchKey, useWorkingCopy } from '../state/workingCopy'
import { editorOptions } from './editorOptions'

function Diff({ id, original, modified, theme }: { id: string; original: string; modified: string; theme: string }) {
  const settings = useEffectiveSettings()
  return (
    <DiffEditor
      original={original}
      modified={modified}
      originalModelPath={`diff:${id}:original`}
      modifiedModelPath={`diff:${id}:modified`}
      theme={theme}
      options={{ ...editorOptions(settings), readOnly: true, originalEditable: false, renderSideBySide: true }}
    />
  )
}

/** Diff of an uncommitted change against what it was edited from. */
export function WorkingDiffView({ path, theme }: { path: string; theme: string }) {
  const repo = useWorkbench((s) => s.repo)
  const change = useWorkingCopy((s) => (repo ? s.changes[branchKey(repo)]?.[path] : undefined))
  if (!change) return <div className="editor-message">No uncommitted changes to {path}.</div>
  return <Diff id={`working:${path}`} original={change.original ?? ''} modified={change.content ?? ''} theme={theme} />
}

function useSide(side: DiffSide) {
  const repo = useWorkbench((s) => s.repo)
  return useFile(repo, side?.path ?? null, side?.ref)
}

/** Diff of a file between two commits, e.g. a PR's base and head. */
export function RefDiffView({ id, base, head, theme }: { id: string; base: DiffSide; head: DiffSide; theme: string }) {
  const original = useSide(base)
  const modified = useSide(head)
  if (original.isLoading || modified.isLoading) return <div className="editor-message">Loading diff…</div>
  const error = original.error ?? modified.error
  if (error) return <div className="editor-message error">{error.message}</div>
  if (original.data?.binary || modified.data?.binary)
    return <div className="editor-message">Binary file changed.</div>
  if (original.data?.too_large || modified.data?.too_large)
    return <div className="editor-message">This file is too large to diff.</div>
  return (
    <Diff id={id} original={original.data?.content ?? ''} modified={modified.data?.content ?? ''} theme={theme} />
  )
}
