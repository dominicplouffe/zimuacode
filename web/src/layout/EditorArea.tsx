import { FileEditor } from '../editor/FileEditor'
import { SettingsEditor } from '../editor/SettingsEditor'
import { MOD } from '../commands/commands'
import { useWorkbench, type Tab } from '../state/store'

const tabTitle = (tab: Tab) => (tab.kind === 'settings' ? 'settings.json' : tab.path.split('/').pop()!)

export function EditorArea({ monacoTheme }: { monacoTheme: string }) {
  const { tabs, activeTab, setActiveTab, closeTab } = useWorkbench()
  const active = tabs.find((t) => t.id === activeTab)

  return (
    <div className="editor-area">
      {tabs.length > 0 && (
        <div className="tabs" role="tablist">
          {tabs.map((tab) => (
            <div
              key={tab.id}
              role="tab"
              aria-selected={tab.id === activeTab}
              className={`tab${tab.id === activeTab ? ' active' : ''}`}
              title={tab.kind === 'file' ? tab.path : 'User settings'}
              onClick={() => setActiveTab(tab.id)}
              onAuxClick={(e) => e.button === 1 && closeTab(tab.id)}
            >
              <span>{tabTitle(tab)}</span>
              <button
                className="tab-close"
                aria-label={`Close ${tabTitle(tab)}`}
                onClick={(e) => {
                  e.stopPropagation()
                  closeTab(tab.id)
                }}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="editor-body">
        {active?.kind === 'file' && <FileEditor key={active.id} path={active.path} theme={monacoTheme} />}
        {active?.kind === 'settings' && <SettingsEditor theme={monacoTheme} />}
        {!active && (
          <div className="welcome">
            <h1>Zimua Code</h1>
            <dl>
              <dt>Go to file</dt>
              <dd>{MOD}P</dd>
              <dt>Show all commands</dt>
              <dd>{MOD}⇧P</dd>
              <dt>Toggle sidebar</dt>
              <dd>{MOD}B</dd>
              <dt>Settings</dt>
              <dd>{MOD},</dd>
            </dl>
          </div>
        )}
      </div>
    </div>
  )
}
