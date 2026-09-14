<template>
  <header class="studio-header">
    <RouterLink to="/" class="studio-brand" :aria-label="t('back')"><svg viewBox="0 0 32 32" aria-hidden="true"><path class="brand-mark" d="M4 15 16 5l12 10M8 13v14h16V13M13 27v-8h6v8" /><path class="brand-bolt" d="M19 3l-5 11h5l-3 14 11-17h-6l3-8" /></svg><span>SAMKY<span class="brand-light"> Studio</span></span></RouterLink>
    <span class="header-location">{{ label || t('workspace') }}</span>
    <div class="header-end"><slot /><button class="theme-toggle" type="button" :aria-label="t(theme === 'dark' ? 'lightMode' : 'darkMode')" :title="t(theme === 'dark' ? 'lightMode' : 'darkMode')" :aria-pressed="theme === 'dark'" @click="toggleTheme"><svg v-if="theme === 'dark'" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg><svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M20.2 15.4A8.5 8.5 0 0 1 8.6 3.8 8.5 8.5 0 1 0 20.2 15.4Z"/></svg></button><select v-model="locale" aria-label="Language" class="language-select"><option value="en">EN</option><option value="vi">VI</option><option value="es">ES</option></select></div>
  </header>
</template>
<script setup>
import { useStudioText } from './i18n'
import { useStudioTheme } from './theme'
defineProps({ label: String })
const { t, locale } = useStudioText()
const { theme, toggleTheme } = useStudioTheme()
</script>
