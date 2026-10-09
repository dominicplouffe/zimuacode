import { useQueryClient } from '@tanstack/react-query'
import { Command } from 'cmdk'
import { useMemo, useState } from 'react'
import { useBranches, useRepos, useSaveSettings, useSettings, useThemes, useTree, withSetting } from '../api/hooks'
import { useWorkbench, type Palette as PaletteKind } from '../state/store'
import { getCommands } from './commands'
import { fuzzyFilter } from './fuzzy'

interface Item {
  id: string
  label: string
  detail?: string
  run: () => void
}

const PLACEHOLDERS: Record<Exclude<PaletteKind, null>, string> = {
  files: 'Search files by name',
  commands: 'Type a command',
  repos: 'Open a repository',
  branches: 'Switch to branch',
  themes: 'Select color theme',
}

function useItems(kind: Exclude<PaletteKind, null>): { items: Item[]; loading: boolean } {
  const queryClient = useQueryClient()
  const { repo, openFile, openRepo, setRef } = useWorkbench()
  const tree = useTree(kind === 'files' ? repo : null)
  const repos = useRepos()
  const branches = useBranches(kind === 'branches' ? repo : null)
  const themes = useThemes()
  const settings = useSettings()
  const saveSettings = useSaveSettings()

  return useMemo(() => {
    switch (kind) {
      case 'files':
        return {
          loading: tree.isLoading,
          items: (tree.data?.entries ?? [])
            .filter((e) => e.type === 'blob')
            .map((e) => ({ id: e.path, label: e.path, run: () => openFile(e.path) })),
        }
      case 'commands':
        return {
          loading: false,
          items: getCommands(queryClient).map((c) => ({
            id: c.id,
            label: c.title,
            detail: c.keybinding,
            run: c.run,
          })),
        }
      case 'repos':
        return {
          loading: repos.isLoading,
          items: (repos.data ?? []).map((r) => ({
            id: r.full_name,
            label: r.full_name,
            detail: r.private ? 'private' : undefined,
            run: () =>
              openRepo({ owner: r.owner, name: r.name, ref: r.default_branch, defaultBranch: r.default_branch }),
          })),
        }
      case 'branches':
        return {
          loading: branches.isLoading,
          items: (branches.data ?? []).map((b) => ({
            id: b.name,
            label: b.name,
            detail: b.name === repo?.ref ? 'current' : b.protected ? 'protected' : undefined,
            run: () => setRef(b.name),
          })),
        }
      case 'themes':
        return {
          loading: themes.isLoading,
          items: (themes.data ?? []).map((t) => ({
            id: t.id,
            label: t.name,
            detail: settings.data?.effective['workbench.theme'] === t.id ? 'current' : undefined,
            run: () =>
              saveSettings.mutate(withSetting(settings.data?.raw ?? '{}', 'workbench.theme', t.id)),
          })),
        }
    }
  }, [kind, tree.data, tree.isLoading, repos.data, repos.isLoading, branches.data, branches.isLoading,
    themes.data, themes.isLoading, settings.data, saveSettings, queryClient, openFile, openRepo, setRef, repo?.ref])
}

function PaletteBody({ kind }: { kind: Exclude<PaletteKind, null> }) {
  const setPalette = useWorkbench((s) => s.setPalette)
  const [query, setQuery] = useState('')
  const { items, loading } = useItems(kind)
  const shown = useMemo(() => fuzzyFilter(items, query, (i) => i.label), [items, query])

  const close = () => setPalette(null)

  return (
    <div className="palette-backdrop" onMouseDown={close}>
      <Command
        className="palette"
        shouldFilter={false}
        label={PLACEHOLDERS[kind]}
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Escape') close()
        }}
      >
        <Command.Input autoFocus value={query} onValueChange={setQuery} placeholder={PLACEHOLDERS[kind]} />
        <Command.List>
          {loading && <Command.Loading>Loading…</Command.Loading>}
          {!loading && <Command.Empty>No results</Command.Empty>}
          {shown.map((item) => (
            <Command.Item
              key={item.id}
              value={item.id}
              onSelect={() => {
                close()
                item.run()
              }}
            >
              <span className="palette-label">{item.label}</span>
              {item.detail && <span className="palette-detail">{item.detail}</span>}
            </Command.Item>
          ))}
        </Command.List>
      </Command>
    </div>
  )
}

export function Palette() {
  const kind = useWorkbench((s) => s.palette)
  // Keyed by kind so switching from commands to files resets the query.
  return kind ? <PaletteBody key={kind} kind={kind} /> : null
}
