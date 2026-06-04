// Фаза 13: тема = режим (auto/light/dark) + акцент-палитра (пресет или своя).
//  - Режим диктует ФОН/ТЕКСТ (как в Telegram): auto = цвета Telegram,
//    light/dark = стандартные нейтральные палитры.
//  - Палитра меняет ТОЛЬКО акцентный цвет (кнопки/ссылки/выделения).
// Переменные инъектируются в <html> из JS (applyTheme).
export type ThemePref = 'auto' | 'light' | 'dark'
type Mode = 'light' | 'dark'

const KEY_MODE = 'theme_pref'
const KEY_PALETTE = 'theme_palette'
const KEY_CUSTOM = 'theme_custom'

export interface Palette {
  id: string
  label: string
  swatch: string      // акцент для light + образец в UI
  swatchDark?: string // акцент для dark (если нужен светлее)
}

// id 'telegram' и 'custom' — особые (см. accentFor). Остальные — пресеты-акценты.
export const PALETTES: Palette[] = [
  { id: 'telegram', label: 'Как в Telegram', swatch: '#3390ec' },
  { id: 'coral', label: 'Коралл', swatch: '#e5715a', swatchDark: '#f08a72' },
  { id: 'terracotta', label: 'Терракот', swatch: '#c85a3c', swatchDark: '#d9724e' },
  { id: 'apricot', label: 'Абрикос', swatch: '#e8765c', swatchDark: '#f5957e' },
  { id: 'ocean', label: 'Океан', swatch: '#2b8a9e', swatchDark: '#4fb3c7' },
  { id: 'sage', label: 'Шалфей', swatch: '#4f8a5b', swatchDark: '#6cbf7a' },
  { id: 'lavender', label: 'Лаванда', swatch: '#7c6bc4', swatchDark: '#a594e6' },
]

// Стандартные нейтральные поверхности (когда режим задан явно light/dark).
const SURFACE: Record<Mode, { bg: string; card: string; secondary: string; text: string; hint: string; separator: string }> = {
  light: { bg: '#ffffff', card: '#ffffff', secondary: '#f1f3f5', text: '#000000', hint: '#8e8e93', separator: 'rgba(0,0,0,0.08)' },
  dark: { bg: '#17212b', card: '#1d2733', secondary: '#232e3c', text: '#ffffff', hint: '#8a9aa9', separator: 'rgba(255,255,255,0.08)' },
}

const DESTRUCTIVE: Record<Mode, string> = { light: '#d64c3c', dark: '#f0796a' }
const DEFAULT_CUSTOM = '#e5715a'

type TgWebApp = { colorScheme?: 'light' | 'dark'; onEvent?: (e: string, cb: () => void) => void }
function tg(): TgWebApp | undefined {
  return (window as unknown as { Telegram?: { WebApp?: TgWebApp } }).Telegram?.WebApp
}

export function getThemePref(): ThemePref {
  const v = localStorage.getItem(KEY_MODE)
  return v === 'light' || v === 'dark' ? v : 'auto'
}
export function getPaletteId(): string {
  const v = localStorage.getItem(KEY_PALETTE)
  if (v === 'custom' || PALETTES.some((p) => p.id === v)) return v as string
  return 'telegram'
}
export function getCustomAccent(): string {
  return localStorage.getItem(KEY_CUSTOM) || DEFAULT_CUSTOM
}

function systemIsDark(): boolean {
  const scheme = tg()?.colorScheme
  if (scheme === 'dark') return true
  if (scheme === 'light') return false
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}
function resolveMode(pref: ThemePref): Mode {
  return pref === 'auto' ? (systemIsDark() ? 'dark' : 'light') : pref
}

function accentFor(paletteId: string, mode: Mode): string {
  if (paletteId === 'telegram') return 'var(--tg-theme-button-color, #3390ec)'
  if (paletteId === 'custom') return getCustomAccent()
  const p = PALETTES.find((x) => x.id === paletteId)
  if (!p) return 'var(--tg-theme-button-color, #3390ec)'
  return mode === 'dark' ? (p.swatchDark ?? p.swatch) : p.swatch
}

export function applyTheme(): void {
  const pref = getThemePref()
  const mode = resolveMode(pref)
  const root = document.documentElement
  root.setAttribute('data-theme', mode)
  const set = (k: string, v: string) => root.style.setProperty(k, v)

  if (pref === 'auto') {
    // Цвета Telegram (фоллбэк по resolved-режиму, если клиент не задал var).
    const f = SURFACE[mode]
    set('--bg', `var(--tg-theme-bg-color, ${f.bg})`)
    set('--card', `var(--tg-theme-bg-color, ${f.card})`)
    set('--secondary-bg', `var(--tg-theme-secondary-bg-color, ${f.secondary})`)
    set('--text', `var(--tg-theme-text-color, ${f.text})`)
    set('--hint', `var(--tg-theme-hint-color, ${f.hint})`)
    set('--separator', `var(--tg-theme-section-separator-color, ${f.separator})`)
  } else {
    const s = SURFACE[mode]
    set('--bg', s.bg)
    set('--card', s.card)
    set('--secondary-bg', s.secondary)
    set('--text', s.text)
    set('--hint', s.hint)
    set('--separator', s.separator)
  }

  const accent = accentFor(getPaletteId(), mode)
  set('--destructive', DESTRUCTIVE[mode])
  set('--accent', accent)
  set('--button-bg', accent)
  set('--button-color', accent)
  set('--button-text', '#ffffff')
  set('--button-text-color', '#ffffff')
  set('--link', accent)
  set('--link-color', accent)
}

export function setThemePref(pref: ThemePref): void {
  localStorage.setItem(KEY_MODE, pref)
  applyTheme()
}
export function setPaletteId(id: string): void {
  localStorage.setItem(KEY_PALETTE, id)
  applyTheme()
}
export function setCustomAccent(hex: string): void {
  localStorage.setItem(KEY_CUSTOM, hex)
  localStorage.setItem(KEY_PALETTE, 'custom')
  applyTheme()
}

let bound = false
export function initTheme(): void {
  applyTheme()
  if (bound) return
  bound = true
  const onChange = () => { if (getThemePref() === 'auto') applyTheme() }
  tg()?.onEvent?.('themeChanged', onChange)
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', onChange)
}
