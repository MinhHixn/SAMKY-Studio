<template>
  <nav v-if="simulationId" class="result-nav" :aria-label="t('resultPages')">
    <RouterLink :to="'/simulation/' + simulationId + '/graph'" :aria-current="active==='graph'?'page':undefined" :class="{active:active==='graph'}"><span class="nav-icon" aria-hidden="true">◉</span>{{ t('graphPage') }}</RouterLink>
    <RouterLink :to="'/simulation/' + simulationId + '/report'" :aria-current="active==='report'?'page':undefined" :class="{active:active==='report'}"><span class="nav-icon" aria-hidden="true">▤</span>{{ t('reportPage') }}</RouterLink>
    <RouterLink :to="'/simulation/' + simulationId + '/interview'" :aria-current="active==='interview'?'page':undefined" :class="{active:active==='interview'}"><span class="nav-icon" aria-hidden="true">◌</span>{{ t('interviewPage') }}</RouterLink>
  </nav>
</template>
<script setup>
import { useStudioText } from './i18n'
defineProps({ simulationId: String, active: String })
const { t } = useStudioText()
</script>
<style scoped>
.result-nav{display:flex;justify-content:center;gap:5px;flex-shrink:0;border-bottom:1px solid var(--line);background:var(--paper);padding:9px 20px}.result-nav a{display:inline-flex;align-items:center;gap:10px;padding:10px 22px;border-radius:6px;font-size:16px;color:var(--muted);text-decoration:none;transition:background .2s,color .2s}.result-nav a:hover{background:var(--soft);color:var(--ink)}.result-nav a.active{background:var(--soft);color:var(--accent);font-weight:600}.nav-icon{font-size:19px;line-height:1;font-weight:400}@media(max-width:700px){.result-nav{padding:8px 10px;gap:2px}.result-nav a{padding:9px 10px;font-size:13px;gap:6px}.nav-icon{font-size:16px}}@media(max-width:360px){.result-nav a{font-size:12px;padding:9px 7px}}
</style>
