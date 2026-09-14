<template>
  <div class="graph-page">
    <StudioHeader :label="t('graphPage')" />
    <StudioResultNav :simulation-id="simulationId" active="graph" />
    <div class="graph-page-toolbar">
      <div class="graph-page-heading"><span class="eyebrow">{{ t('results') }}</span><h1>{{ t('graph') }}</h1></div>
      <div class="graph-page-actions" role="group" :aria-label="t('resultPages')">
        <button type="button" class="split-button" :class="{active:split==='report'}" :aria-pressed="split==='report'" @click="setSplit(split==='report'?'':'report')">▤ <span>{{ t('splitReport') }}</span></button>
        <button type="button" class="split-button" :class="{active:split==='interview'}" :aria-pressed="split==='interview'" @click="setSplit(split==='interview'?'':'interview')">◌ <span>{{ t('splitInterview') }}</span></button>
        <button v-if="split" type="button" class="text-button close-split" @click="setSplit('')">× <span>{{ t('closeSplit') }}</span></button>
      </div>
    </div>
    <p v-if="error" class="graph-page-error error-message" role="alert">{{ error }} <button class="text-button" type="button" @click="loadGraph">{{ t('refreshGraph') }}</button></p>
    <main class="graph-stage" :class="{split:!!split}">
      <div class="graph-region"><StudioGraph :data="graph" @refresh="loadGraph" /></div>
      <section v-if="split" class="companion-pane" :aria-label="t(split==='report'?'reportPage':'interviewPage')">
        <div class="companion-head"><span>{{ t(split==='report'?'reportPage':'interviewPage') }}</span><RouterLink :to="'/simulation/' + simulationId + '/' + split" class="text-button">{{ t('openFullPage') }} ↗</RouterLink></div>
        <EmbeddedReport v-if="split==='report'" embedded />
        <EmbeddedInterview v-else embedded />
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import service from '../api'
import StudioHeader from '../studio/StudioHeader.vue'
import StudioResultNav from '../studio/StudioResultNav.vue'
import StudioGraph from '../studio/StudioGraph.vue'
import { useStudioText } from '../studio/i18n'

const EmbeddedReport = defineAsyncComponent(() => import('./StudioReport.vue'))
const EmbeddedInterview = defineAsyncComponent(() => import('./StudioInterview.vue'))
const route = useRoute(), router = useRouter(), { t } = useStudioText()
const simulationId = computed(() => String(route.params.simulationId || ''))
const split = computed(() => ['report', 'interview'].includes(route.query.with) ? route.query.with : '')
const graph = ref(null), error = ref('')
let request = 0

function setSplit(value) {
  router.replace({ name: 'SimulationGraph', params: { simulationId: simulationId.value }, query: { ...route.query, with: value || undefined } })
}

async function loadGraph() {
  const current = ++request, id = simulationId.value
  graph.value = null
  error.value = ''
  if (!id) return
  try {
    const response = await service.get('/api/simulation/' + id)
    const simulation = response.data || response
    let graphId = simulation.graph_id
    if (!graphId && simulation.project_id) {
      const projectResponse = await service.get('/api/graph/project/' + simulation.project_id)
      graphId = (projectResponse.data || projectResponse).graph_id
    }
    if (!graphId) throw new Error(t('graphUnavailable'))
    const graphResponse = await service.get('/api/graph/data/' + graphId)
    if (current === request) graph.value = graphResponse.data || graphResponse
  } catch (cause) {
    if (current === request) error.value = cause.response?.data?.error || cause.message
  }
}

onMounted(loadGraph)
watch(simulationId, loadGraph)
</script>

<style scoped>
.graph-page{height:100dvh;min-height:580px;display:flex;flex-direction:column}
.graph-page-toolbar{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:15px 4.2vw;border-bottom:1px solid var(--line)}
.graph-page-heading{display:flex;align-items:center;gap:16px;min-width:0}
.graph-page-heading h1{font-size:19px;font-weight:550;letter-spacing:-.4px;white-space:nowrap}
.graph-page-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.split-button{display:flex;align-items:center;gap:9px;min-height:38px;padding:7px 13px;border:1px solid var(--line);border-radius:6px;background:var(--surface);font-size:13px;color:var(--muted)}
.split-button:hover,.split-button.active{border-color:var(--accent);background:var(--soft);color:var(--accent)}
.close-split{padding:7px 4px;white-space:nowrap}
.graph-page-error{margin:12px 4.2vw}
.graph-page-error .text-button{color:var(--danger);text-decoration:underline}
.graph-stage{flex:1;min-height:0;display:grid;grid-template-columns:minmax(0,1fr)}
.graph-stage.split{grid-template-columns:minmax(0,1fr) minmax(440px,47%)}
.graph-region{display:flex;min-width:0;min-height:0}
.companion-pane{min-width:0;min-height:0;display:flex;flex-direction:column;overflow:hidden;border-left:1px solid var(--line);background:var(--surface-tint)}
.companion-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-shrink:0;padding:10px 17px;border-bottom:1px solid var(--line);font-size:14px;font-weight:600}
.companion-head .text-button{font-size:12px;white-space:nowrap}
@media(max-width:960px){.graph-page{height:auto;min-height:100dvh}.graph-page-toolbar{padding:13px 20px;align-items:flex-start;flex-wrap:wrap}.graph-page-actions{justify-content:flex-start}.graph-stage.split{display:flex;flex-direction:column}.graph-region{height:55dvh;min-height:390px}.companion-pane{height:75dvh;min-height:600px;border-left:0;border-top:1px solid var(--line)}}
@media(max-width:540px){.graph-page-heading .eyebrow{display:none}.graph-page-toolbar{gap:12px}.graph-page-actions{width:100%;flex-wrap:nowrap;gap:5px}.split-button{padding:7px 8px;font-size:12px;flex:1;justify-content:center}.close-split{font-size:18px}.close-split span{display:none}.graph-stage:not(.split) .graph-region{height:calc(100dvh - 190px);min-height:420px}}
</style>
