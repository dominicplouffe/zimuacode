import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { RepoRef } from '../state/store'

export const useMe = () => useQuery({ queryKey: ['me'], queryFn: api.me, retry: false })

export const useSettings = () =>
  useQuery({ queryKey: ['settings'], queryFn: api.settings, staleTime: Infinity })

export const useThemes = () =>
  useQuery({ queryKey: ['themes'], queryFn: api.themes, staleTime: Infinity })

export const useRepos = () => useQuery({ queryKey: ['repos'], queryFn: () => api.repos() })

export const useBranches = (repo: RepoRef | null) =>
  useQuery({
    queryKey: ['branches', repo?.owner, repo?.name],
    queryFn: () => api.branches(repo!.owner, repo!.name),
    enabled: repo !== null,
  })

export const useTree = (repo: RepoRef | null) =>
  useQuery({
    queryKey: ['tree', repo?.owner, repo?.name, repo?.ref],
    queryFn: () => api.tree(repo!.owner, repo!.name, repo!.ref),
    enabled: repo !== null,
  })

/** A file at a ref. Pass a commit SHA where possible; it never changes, so it caches forever. */
export const useFile = (repo: RepoRef | null, path: string | null, ref: string | undefined) =>
  useQuery({
    queryKey: ['file', repo?.owner, repo?.name, ref, path],
    queryFn: () => api.file(repo!.owner, repo!.name, path!, ref!),
    enabled: repo !== null && path !== null && ref !== undefined,
    staleTime: Infinity,
  })

export const usePulls = (repo: RepoRef | null, state: 'open' | 'closed') =>
  useQuery({
    queryKey: ['pulls', repo?.owner, repo?.name, state],
    queryFn: () => api.pulls(repo!.owner, repo!.name, state),
    enabled: repo !== null,
  })

/** The open PR whose head is the current branch, if any. */
export const useBranchPull = (repo: RepoRef | null) =>
  useQuery({
    queryKey: ['pulls', repo?.owner, repo?.name, 'branch', repo?.ref],
    queryFn: async () => (await api.pulls(repo!.owner, repo!.name, 'open', repo!.ref))[0] ?? null,
    enabled: repo !== null,
  })

export const usePull = (repo: RepoRef | null, number: number) =>
  useQuery({
    queryKey: ['pull', repo?.owner, repo?.name, number],
    queryFn: () => api.pull(repo!.owner, repo!.name, number),
    enabled: repo !== null,
  })

export const usePullFiles = (repo: RepoRef | null, number: number, headSha: string | undefined) =>
  useQuery({
    queryKey: ['pullFiles', repo?.owner, repo?.name, number, headSha],
    queryFn: () => api.pullFiles(repo!.owner, repo!.name, number),
    enabled: repo !== null && headSha !== undefined,
  })

export const usePullTimeline = (repo: RepoRef | null, number: number) =>
  useQuery({
    queryKey: ['timeline', repo?.owner, repo?.name, number],
    queryFn: () => api.pullTimeline(repo!.owner, repo!.name, number),
    enabled: repo !== null,
  })

export const useChecks = (repo: RepoRef | null, sha: string | undefined) =>
  useQuery({
    queryKey: ['checks', repo?.owner, repo?.name, sha],
    queryFn: () => api.checks(repo!.owner, repo!.name, sha!),
    enabled: repo !== null && sha !== undefined,
    // Running checks change; poll while the tab is open.
    refetchInterval: (query) =>
      query.state.data?.some((c) => c.status !== 'completed') ? 15_000 : false,
  })

/** Effective settings, or undefined until loaded. */
export function useEffectiveSettings(): Record<string, unknown> | undefined {
  return useSettings().data?.effective
}

export function useSaveSettings() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.saveSettings,
    onSuccess: (data) => client.setQueryData(['settings'], data),
  })
}

/** Returns settings.json text with one key changed, keeping the user's other keys. */
export function withSetting(raw: string, key: string, value: unknown): string {
  let current: Record<string, unknown> = {}
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) current = parsed
  } catch {
    // Unparseable text can't be saved anyway; start from an empty object.
  }
  return JSON.stringify({ ...current, [key]: value }, null, 2)
}

export const useProviders = () => useQuery({ queryKey: ['providers'], queryFn: api.providers })

export const useTasks = (repo: RepoRef | null) =>
  useQuery({
    queryKey: ['tasks', repo?.owner, repo?.name],
    queryFn: () => api.tasks(repo?.owner, repo?.name),
    // Keep the list (and the activity bar badge) current while agents are working.
    refetchInterval: (query) =>
      query.state.data?.some((t) => t.status === 'running' || t.status === 'preparing') ? 5_000 : 30_000,
  })

export const useTask = (id: string) =>
  useQuery({ queryKey: ['task', id], queryFn: () => api.task(id) })

export const useTaskChanges = (id: string, enabled: boolean) =>
  useQuery({ queryKey: ['taskChanges', id], queryFn: () => api.taskChanges(id), enabled })

export const useTaskFile = (id: string, path: string, side: 'base' | 'working') =>
  useQuery({ queryKey: ['taskFile', id, side, path], queryFn: () => api.taskFile(id, path, side) })
