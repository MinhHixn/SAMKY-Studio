import { ref } from 'vue'

const STORAGE_KEY = 'sam:theme'
const theme = ref('light')

export function setStudioTheme(value) {
  theme.value = value === 'dark' ? 'dark' : 'light'
  document.documentElement.dataset.theme = theme.value
  document.documentElement.style.colorScheme = theme.value
  try { localStorage.setItem(STORAGE_KEY, theme.value) } catch { /* Storage may be disabled. */ }
}

export function initStudioTheme() {
  let saved
  try { saved = localStorage.getItem(STORAGE_KEY) } catch { /* Storage may be disabled. */ }
  setStudioTheme(saved === 'dark' ? 'dark' : 'light')
}

export function useStudioTheme() {
  return { theme, toggleTheme: () => setStudioTheme(theme.value === 'dark' ? 'light' : 'dark') }
}
