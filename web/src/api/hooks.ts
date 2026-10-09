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

export const useFile = (repo: RepoRef | null, path: string) =>
  useQuery({
    queryKey: ['file', repo?.owner, repo?.name, repo?.ref, path],
    queryFn: () => api.file(repo!.owner, repo!.name, path, repo!.ref),
    enabled: repo !== null,
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
