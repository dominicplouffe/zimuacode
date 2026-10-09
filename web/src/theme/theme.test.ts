import { describe, expect, it } from 'vitest'
import { cssVarName, themeCssVars, toMonacoTheme } from './theme'

const theme = {
  id: 'dark',
  name: 'Dark',
  type: 'dark',
  colors: { 'editor.background': '#1e1e1e', 'sideBar.background': '#181818' },
  tokenColors: [
    { scope: ['comment', 'punctuation.definition.comment'], settings: { foreground: '#6a9955', fontStyle: 'italic' } },
    { scope: 'keyword, storage', settings: { foreground: '#569cd6' } },
    { settings: { foreground: '#ffffff' } },
  ],
}

describe('theme', () => {
  it('maps color keys to CSS variables', () => {
    expect(cssVarName('sideBar.background')).toBe('--sideBar-background')
    expect(themeCssVars(theme)).toEqual({
      '--editor-background': '#1e1e1e',
      '--sideBar-background': '#181818',
    })
  })

  it('builds a Monaco theme from token colors', () => {
    const m = toMonacoTheme(theme)
    expect(m.base).toBe('vs-dark')
    expect(m.rules).toEqual([
      { token: 'comment', foreground: '6a9955', fontStyle: 'italic' },
      { token: 'punctuation.definition.comment', foreground: '6a9955', fontStyle: 'italic' },
      { token: 'keyword', foreground: '569cd6' },
      { token: 'storage', foreground: '569cd6' },
    ])
  })

  it('picks the base theme by type', () => {
    expect(toMonacoTheme({ ...theme, type: 'light' }).base).toBe('vs')
    expect(toMonacoTheme({ ...theme, type: 'hc' }).base).toBe('hc-black')
  })
})
