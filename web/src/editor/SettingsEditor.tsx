import Editor, { type OnMount } from '@monaco-editor/react'
import { useEffect, useRef, useState } from 'react'
import { useEffectiveSettings, useSaveSettings, useSettings } from '../api/hooks'
import { editorOptions } from './editorOptions'
import { monaco } from './monaco'

const MODEL_PATH = 'zimua://user/settings.json'

export function SettingsEditor({ theme }: { theme: string }) {
  const settings = useSettings()
  const effective = useEffectiveSettings()
  const save = useSaveSettings()
  const [dirty, setDirty] = useState(false)
  const saveRef = useRef<() => void>(() => {})
  const syncing = useRef(false)

  useEffect(() => {
    if (!settings.data) return
    monaco.json.jsonDefaults.setDiagnosticsOptions({
      validate: true,
      allowComments: false,
      schemas: [
        { uri: 'zimua://schemas/settings.json', fileMatch: [MODEL_PATH], schema: settings.data.json_schema },
      ],
    })
  }, [settings.data])

  // Settings can change elsewhere (e.g. the theme picker). Show that unless there are unsaved edits.
  const raw = settings.data?.raw
  useEffect(() => {
    const model = monaco.editor.getModel(monaco.Uri.parse(MODEL_PATH))
    if (raw === undefined || !model || dirty || model.getValue() === raw) return
    syncing.current = true
    model.setValue(raw)
    syncing.current = false
  }, [raw, dirty])

  const onMount: OnMount = (editor, m) => {
    editor.addCommand(m.KeyMod.CtrlCmd | m.KeyCode.KeyS, () => saveRef.current())
  }

  saveRef.current = () => {
    const model = monaco.editor.getModel(monaco.Uri.parse(MODEL_PATH))
    if (!model) return
    save.mutate(model.getValue(), { onSuccess: () => setDirty(false) })
  }

  if (!settings.data) return <div className="editor-message">Loading settings…</div>

  return (
    <div className="settings-editor">
      <div className="editor-toolbar">
        <span>settings.json{dirty ? ' •' : ''}</span>
        {save.error && <span className="error">{save.error.message}</span>}
        <button className="button" disabled={!dirty || save.isPending} onClick={() => saveRef.current()}>
          Save
        </button>
      </div>
      <Editor
        path={MODEL_PATH}
        language="json"
        defaultValue={settings.data.raw}
        theme={theme}
        onMount={onMount}
        onChange={() => {
          if (!syncing.current) setDirty(true)
        }}
        options={editorOptions(effective)}
      />
    </div>
  )
}
