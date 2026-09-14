<template>
  <section class="society-canvas" :class="{ maximized }" :aria-label="t('graph')">
    <GraphPanel :graph-data="data" :current-phase="0" :is-simulating="false" @refresh="$emit('refresh')" @toggle-maximize="toggleMaximize" />
    <div v-if="!data" class="graph-empty"><div class="empty-orbits" aria-hidden="true"><i></i><i></i><i></i><b></b></div><h2>{{ t('waiting') }}</h2><p>{{ t('waitingHint') }}</p></div>
  </section>
</template>
<script setup>
import { nextTick, ref } from 'vue'
import GraphPanel from '../components/GraphPanel.vue'
import { useStudioText } from './i18n'
defineProps({ data: Object })
defineEmits(['refresh'])
const { t } = useStudioText()
const maximized = ref(false)
function toggleMaximize() { maximized.value = !maximized.value; nextTick(() => window.dispatchEvent(new Event('resize'))) }
</script>
<style scoped>
.society-canvas{position:relative;min-height:240px;flex:1;overflow:hidden;background:var(--paper)}
.society-canvas.maximized{position:fixed;z-index:1000;inset:0}
.society-canvas :deep(.graph-panel){background-color:var(--paper);background-image:radial-gradient(var(--graph-grid) 1px,transparent 1px)}
.society-canvas :deep(.panel-title){font-size:14px;font-weight:500;color:var(--ink)}
.society-canvas :deep(.tool-btn){box-shadow:none}
.society-canvas :deep(.icon-refresh),.society-canvas :deep(.icon-maximize){font-size:19px;line-height:1}
.graph-empty{position:absolute;top:44%;left:50%;transform:translate(-50%,-50%);text-align:center;width:90%;pointer-events:none}.graph-empty h2{font-size:20px;letter-spacing:-.6px;font-weight:450;margin-top:30px}.graph-empty p{font-size:14px;color:var(--muted);margin-top:11px}.empty-orbits{position:relative;width:120px;height:100px;margin:auto}.empty-orbits i{position:absolute;inset:18px 0;border:1px solid var(--line);border-radius:50%;transform:rotate(-30deg)}.empty-orbits i:nth-child(2){transform:rotate(30deg)}.empty-orbits i:nth-child(3){transform:rotate(90deg)}.empty-orbits b{position:absolute;top:46px;left:56px;width:8px;height:8px;border-radius:50%;background:var(--accent)}
</style>
