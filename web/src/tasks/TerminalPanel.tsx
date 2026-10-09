import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { useEffectiveSettings, useTask } from '../api/hooks'
import { useWorkbench } from '../state/store'

function cssVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

/** A shell in the task's workspace. It keeps running on the server between connections. */
function TaskTerminal({ taskId }: { taskId: string }) {
  const container = useRef<HTMLDivElement>(null)
  const settings = useEffectiveSettings()
  const [state, setState] = useState<'connecting' | 'open' | 'closed' | 'exited'>('connecting')
  const [generation, setGeneration] = useState(0)

  useEffect(() => {
    if (!container.current) return
    const term = new Terminal({
      fontFamily: (settings?.['editor.fontFamily'] as string) ?? 'monospace',
      fontSize: (settings?.['editor.fontSize'] as number) ?? 13,
      cursorBlink: true,
      scrollback: 5000,
      theme: {
        background: cssVar('--panel-background', '#181818'),
        foreground: cssVar('--editor-foreground', '#d4d4d4'),
        cursor: cssVar('--editorCursor-foreground', '#aeafad'),
        selectionBackground: cssVar('--editor-selectionBackground', '#264f78'),
      },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(container.current)
    fit.fit()

    const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${scheme}://${location.host}/api/tasks/${taskId}/terminal`)
    ws.binaryType = 'arraybuffer'
    const sendSize = () => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
    }
    ws.onopen = () => {
      setState('open')
      sendSize()
      term.focus()
    }
    ws.onmessage = (message) => {
      if (message.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(message.data))
      } else if (JSON.parse(message.data).type === 'exit') {
        term.write('\r\n\x1b[2m[shell exited]\x1b[0m\r\n')
        setState('exited')
      }
    }
    ws.onclose = () => setState((s) => (s === 'exited' ? s : 'closed'))
    const input = term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'input', data }))
    })
    const observer = new ResizeObserver(() => {
      fit.fit()
      sendSize()
    })
    observer.observe(container.current)

    return () => {
      observer.disconnect()
      input.dispose()
      ws.close()
      term.dispose()
    }
  }, [taskId, generation, settings])

  return (
    <>
      {(state === 'closed' || state === 'exited') && (
        <div className="terminal-banner">
          {state === 'exited' ? 'The shell exited.' : 'Disconnected.'}{' '}
          <button className="link-button" onClick={() => setGeneration((g) => g + 1)}>
            {state === 'exited' ? 'Start a new shell' : 'Reconnect'}
          </button>
        </div>
      )}
      <div className="terminal" ref={container} data-testid="terminal-view" />
    </>
  )
}

export function TerminalPanel() {
  const taskId = useWorkbench((s) => s.terminalTask)
  const task = useTask(taskId ?? '')
  if (!taskId) return null
  return (
    <div className="panel">
      <div className="panel-header">
        <span>Terminal · {task.data?.title ?? 'task'}</span>
        <span className="panel-actions">
          <button
            className="link-button"
            title="End the shell and everything running in it"
            onClick={async () => {
              await api.closeTerminal(taskId)
              useWorkbench.setState({ terminalTask: null })
            }}
          >
            Kill
          </button>
          <button
            className="header-action"
            aria-label="Hide terminal"
            title="Hide (the shell keeps running)"
            onClick={() => useWorkbench.setState({ terminalTask: null })}
          >
            ×
          </button>
        </span>
      </div>
      <TaskTerminal key={taskId} taskId={taskId} />
    </div>
  )
}
