import type { editor } from 'monaco-editor'

/** Maps the user's editor.* settings to Monaco options. */
export function editorOptions(settings: Record<string, unknown> | undefined): editor.IStandaloneEditorConstructionOptions {
  const s = settings ?? {}
  return {
    fontSize: s['editor.fontSize'] as number | undefined,
    fontFamily: s['editor.fontFamily'] as string | undefined,
    tabSize: s['editor.tabSize'] as number | undefined,
    wordWrap: s['editor.wordWrap'] as 'off' | 'on' | undefined,
    minimap: { enabled: Boolean(s['editor.minimap']) },
    automaticLayout: true,
    scrollBeyondLastLine: false,
    renderWhitespace: 'selection',
    smoothScrolling: true,
  }
}
