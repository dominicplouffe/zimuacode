import type { editor } from 'monaco-editor'
import type { Theme } from '../api/client'

/** "sideBar.background" → "--sideBar-background", so CSS can read VS Code theme colors. */
export function cssVarName(colorKey: string): string {
  return `--${colorKey.replace(/\./g, '-')}`
}

export function themeCssVars(theme: Theme): Record<string, string> {
  return Object.fromEntries(
    Object.entries(theme.colors).map(([key, value]) => [cssVarName(key), value]),
  )
}

const BASES: Record<string, editor.BuiltinTheme> = { light: 'vs', dark: 'vs-dark', hc: 'hc-black' }

function hex(color: string): string {
  return color.replace(/^#/, '')
}

/** Converts a VS Code color theme to a Monaco theme. Monaco matches token rules by prefix. */
export function toMonacoTheme(theme: Theme): editor.IStandaloneThemeData {
  const rules: editor.ITokenThemeRule[] = []
  for (const entry of theme.tokenColors) {
    const settings = (entry.settings ?? {}) as { foreground?: string; fontStyle?: string }
    const scopes: string[] = Array.isArray(entry.scope)
      ? (entry.scope as string[])
      : typeof entry.scope === 'string'
        ? entry.scope.split(',').map((s: string) => s.trim())
        : []
    for (const token of scopes) {
      rules.push({
        token,
        ...(settings.foreground ? { foreground: hex(settings.foreground) } : {}),
        ...(settings.fontStyle ? { fontStyle: settings.fontStyle } : {}),
      })
    }
  }
  return {
    base: BASES[theme.type] ?? 'vs-dark',
    inherit: true,
    rules,
    colors: theme.colors,
  }
}

export function monacoThemeId(theme: Theme): string {
  return `zimua-${theme.id}`
}
