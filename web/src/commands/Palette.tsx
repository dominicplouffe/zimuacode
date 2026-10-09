import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { Command } from 'cmdk'
import { useMemo, useState } from 'react'
import { api } from '../api/client'
import {
  useBranches,
  useChecks,
  useRepos,
  useSaveSettings,
  useSettings,
  useThemes,
  useTree,
  withSetting,
} from '../api/hooks'
import { openCheck, STATE_ICON, checkState } from '../pulls/Checks'
import { useWorkbench, type Palette as PaletteKind, type RepoRef } from '../state/store'
import { branchKey, useWorkingCopy } from '../state/workingCopy'
import { getCommands } from './commands'
import { fuzzyFilter } from './fuzzy'

type Kind = Exclude<PaletteKind, null>

interface Item {
  id: string
  label: string
  detail?: string
  run: () => void
}

const PLACEHOLDERS: Record<Kind, string> = {
  files: 'Search files by name',
  commands: 'Type a command',
  repos: 'Open a repository',
  branches: 'Switch to branch',
  themes: 'Select color theme',
  newFile: 'New file path, e.g. src/utils/date.ts',
  newBranch: 'New branch name (from the current branch)',
  deleteBranch: 'Delete branch',
  checks: 'Checks on the current branch',
}

// Modes where the typed text is the input itself, not a filter.
const FREE_TEXT: Kind[] = ['newFile', 'newBranch']

function fail(e: unknown) {
  useWorkbench.getState().notify(e instanceof Error ? e.message : String(e), true)
}

async function createBranch(queryClient: QueryClient, repo: RepoRef, name: string, fromSha: string) {
  try {
    await api.createBranch(repo.owner, repo.name, name, fromSha)
    await queryClient.invalidateQueries({ queryKey: ['branches'] })
    useWorkbench.getState().setRef(name)
    useWorkbench.getState().notify(`Created branch ${name}`)
  } catch (e) {
    fail(e)
  }
}

async function deleteBranch(queryClient: QueryClient, repo: RepoRef, name: string) {
  if (!window.confirm(`Delete branch ${name} on GitHub? This can't be undone here.`)) return
  try {
    await api.deleteBranch(repo.owner, repo.name, name)
    await queryClient.invalidateQueries({ queryKey: ['branches'] })
    useWorkbench.getState().notify(`Deleted branch ${name}`)
  } catch (e) {
    fail(e)
  }
}

function useItems(kind: Kind, query: string): { items: Item[]; loading: boolean } {
  const queryClient = useQueryClient()
  const { repo, openFile, openRepo, setRef } = useWorkbench()
  const tree = useTree(repo)
  const repos = useRepos()
  const branches = useBranches(kind === 'branches' || kind === 'deleteBranch' ? repo : null)
  const checks = useChecks(kind === 'checks' ? repo : null, tree.data?.commit_sha)
  const themes = useThemes()
  const settings = useSettings()
  const saveSettings = useSaveSettings()
  const changes = useWorkingCopy((s) => (repo ? s.changes[branchKey(repo)] : undefined))
  const createFile = useWorkingCopy((s) => s.create)

  return useMemo((): { items: Item[]; loading: boolean } => {
    const text = query.trim()
    switch (kind) {
      case 'files': {
        const paths = new Set((tree.data?.entries ?? []).filter((e) => e.type === 'blob').map((e) => e.path))
        for (const c of Object.values(changes ?? {})) if (c.original === null) paths.add(c.path)
        return {
          loading: tree.isLoading,
          items: [...paths].map((path) => ({ id: path, label: path, run: () => openFile(path) })),
        }
      }
      case 'commands':
        return {
          loading: false,
          items: getCommands(queryClient).map((c) => ({ id: c.id, label: c.title, detail: c.keybinding, run: c.run })),
        }
      case 'repos':
        return {
          loading: repos.isLoading,
          items: (repos.data ?? []).map((r) => ({
            id: r.full_name,
            label: r.full_name,
            detail: r.private ? 'private' : undefined,
            run: () => openRepo({ owner: r.owner, name: r.name, ref: r.default_branch, defaultBranch: r.default_branch }),
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
      case 'deleteBranch':
        return {
          loading: branches.isLoading,
          items: (branches.data ?? [])
            .filter((b) => b.name !== repo?.defaultBranch && b.name !== repo?.ref)
            .map((b) => ({ id: b.name, label: b.name, run: () => deleteBranch(queryClient, repo!, b.name) })),
        }
      case 'themes':
        return {
          loading: themes.isLoading,
          items: (themes.data ?? []).map((t) => ({
            id: t.id,
            label: t.name,
            detail: settings.data?.effective['workbench.theme'] === t.id ? 'current' : undefined,
            run: () => saveSettings.mutate(withSetting(settings.data?.raw ?? '{}', 'workbench.theme', t.id)),
          })),
        }
      case 'checks':
        return {
          loading: checks.isLoading,
          items: (checks.data ?? []).map((c) => ({
            id: `${c.kind}:${c.id}`,
            label: `${STATE_ICON[checkState(c)]} ${c.name}`,
            detail: c.has_logs ? 'show log' : c.url ? 'open' : undefined,
            run: () => openCheck(c),
          })),
        }
      case 'newFile': {
        const path = text.replace(/^\/+/, '')
        if (!path || !repo) return { loading: false, items: [] }
        const exists =
          tree.data?.entries.some((e) => e.path === path) || changes?.[path] !== undefined
        return {
          loading: false,
          items: [
            exists
              ? { id: 'open', label: `Open ${path}`, detail: 'already exists', run: () => openFile(path) }
              : {
                  id: 'create',
                  label: `Create ${path}`,
                  run: () => {
                    createFile(branchKey(repo), path)
                    openFile(path)
                  },
                },
          ],
        }
      }
      case 'newBranch': {
        const sha = tree.data?.commit_sha
        if (!text || !repo || !sha) return { loading: tree.isLoading, items: [] }
        return {
          loading: false,
          items: [
            {
              id: 'create',
              label: `Create branch ${text}`,
              detail: `from ${repo.ref}`,
              run: () => createBranch(queryClient, repo, text, sha),
            },
          ],
        }
      }
    }
  }, [kind, query, tree.data, tree.isLoading, repos.data, repos.isLoading, branches.data, branches.isLoading,
    checks.data, checks.isLoading, themes.data, themes.isLoading, settings.data, saveSettings, queryClient,
    openFile, openRepo, setRef, repo, changes, createFile])
}

function PaletteBody({ kind }: { kind: Kind }) {
  const setPalette = useWorkbench((s) => s.setPalette)
  const [query, setQuery] = useState('')
  const { items, loading } = useItems(kind, query)
  const freeText = FREE_TEXT.includes(kind)
  const shown = useMemo(
    () => (freeText ? items : fuzzyFilter(items, query, (i) => i.label)),
    [items, query, freeText],
  )

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
          {!loading && !freeText && <Command.Empty>No results</Command.Empty>}
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
