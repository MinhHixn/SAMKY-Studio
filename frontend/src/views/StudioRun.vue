<template>
  <div class="run-workspace">
    <StudioHeader :label="name || t('new')"><button v-if="phase === 'running'" class="text-button" :disabled="stopping" @click="stop">{{ t(stopping ? 'stopping' : 'stop') }}</button></StudioHeader>
    <StudioGraph :data="graph" @refresh="refreshGraph" />
    <StudioProgress :title="t(error ? 'failed' : phase)" :phase="phase" :substage="taskDetail.current_stage" :stage-description="taskDetail.item_description" :item-current="Number(taskDetail.current_item)||0" :item-total="Number(taskDetail.total_items)||0" :eta-seconds="etaSeconds" :stalled="stalled" :value="progress" :detail="roundDetail" :done="phase === 'completed'" :error="error" :notice="notice ? t('reconnecting') : ''">
      <template v-if="['completed','stopped'].includes(phase)"><RouterLink class="secondary-button" :to="'/simulation/' + simulationId + '/graph'">{{ t('graphPage') }} ↗</RouterLink><RouterLink class="secondary-button" :to="'/simulation/' + simulationId + '/report'">{{ t('makeReport') }} ↗</RouterLink><RouterLink class="primary-button" :to="'/simulation/' + simulationId + '/interview'">{{ t('interview') }} →</RouterLink></template>
      <template v-else-if="error"><button v-if="canRetry" class="secondary-button" @click="resume">{{ t('resume') }}</button><RouterLink class="primary-button" to="/">{{ t('back') }}</RouterLink></template>
    </StudioProgress>
  </div>
</template>
<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import service from '../api'
import StudioHeader from '../studio/StudioHeader.vue'
import StudioGraph from '../studio/StudioGraph.vue'
import StudioProgress from '../studio/StudioProgress.vue'
import { useStudioText } from '../studio/i18n'
import { getPendingUpload, clearPendingUpload } from '../store/pendingUpload'
import { loadWorkspace, saveWorkspace, runProgress, remainingSeconds, DEFAULT_ROUNDS } from '../studio/runState'
const { t } = useStudioText(), route = useRoute(), router = useRouter()
const name = ref(''), graph = ref(null), phase = ref('uploading'), progress = ref(null), error = ref(''), notice = ref(false), stopping = ref(false), simulationId = ref(''), projectId = ref(''), state = ref({}), taskDetail = ref({}), clock = ref(Date.now())
let active = true, graphTimer, clockTimer, graphBusy = false, settings = { rounds:DEFAULT_ROUNDS, platform:'parallel' }, prepareTask = '', graphId = '', running = false, stageSample = null, lastProgressAt = Date.now()
const canRetry = computed(() => Boolean(projectId.value || simulationId.value || getPendingUpload().isPending))
const roundDetail = computed(() => {if (phase.value !== 'running' && phase.value !== 'completed' && phase.value !== 'stopped') return '';const result = runProgress(state.value,settings.platform);return `${t('round')} ${result.round} ${t('of')} ${result.total || settings.rounds}`})
const etaSeconds = computed(() => {
  if (phase.value === 'running') {
    const started = Date.parse(state.value.started_at)
    const result = runProgress(state.value,settings.platform)
    return Number.isFinite(started) ? remainingSeconds(result.round,result.total,(clock.value-started)/1000) : null
  }
  const detail = taskDetail.value
  return phase.value === 'preparing' && stageSample?.key === detail.current_stage && stageSample?.total === Number(detail.total_items)
    ? remainingSeconds(detail.current_item,detail.total_items,(clock.value-stageSample.at)/1000,stageSample.first) : null
})
const stalled = computed(() => ['building','preparing','running'].includes(phase.value) && clock.value-lastProgressAt > 120000)
function observeTask(task) {
  const detail=task.progress_detail||{},key=detail.current_stage
  if (key && (stageSample?.key !== key || stageSample.total !== Number(detail.total_items))) stageSample={key,total:Number(detail.total_items),first:Number(detail.current_item)||0,at:Date.now()}
  if (key !== taskDetail.value.current_stage || Number(detail.current_item||0)!==Number(taskDetail.value.current_item||0) || Number(task.progress)!==progress.value) lastProgressAt=Date.now()
  taskDetail.value=detail
  progress.value=key && Number.isFinite(Number(detail.stage_progress)) ? Number(detail.stage_progress) : Number.isFinite(Number(task.progress)) ? Number(task.progress) : null
}
function ensureActive() { if (!active) throw new Error('Workspace closed') }
async function get(url, options) { const response = await service.get(url,options);ensureActive();return response.data }
async function post(url,data,requestOptions) {
  ensureActive()
  // Override the API client's JSON default so Flask receives request.files.
  const options=data instanceof FormData ? {headers:{'Content-Type':'multipart/form-data'},...requestOptions} : requestOptions
  const response=await service.post(url,data,options)
  ensureActive()
  return response.data
}
async function pause() { await new Promise(resolve => setTimeout(resolve,2000));ensureActive() }
function remember() {const data = {...settings,simulationId:simulationId.value,prepareTask};if(projectId.value) saveWorkspace(projectId.value,data);if(simulationId.value)saveWorkspace(simulationId.value,data)}
async function refreshGraph() { if (!active || graphBusy) return;graphBusy = true;try {if(!graphId && projectId.value){const project=await get('/api/graph/project/'+projectId.value);graphId=project.graph_id||''}if(!graphId)return;const data = await get('/api/graph/data/' + graphId);if(active && JSON.stringify(graph.value)!==JSON.stringify(data))graph.value=data} catch { /* A graph refresh does not interrupt a running simulation. */ } finally {graphBusy = false} }
async function waitTask(url,body) {
  let failures = 0
  while (active) {
    let task
    try { task = body ? await post(url,body) : await get(url); failures = 0; notice.value = false } catch(e) { ensureActive();if (++failures >= 5 || (e.response?.status && e.response.status < 500)) throw e;notice.value = true;await pause();continue }
    if (['failed','error'].includes(task.status)) throw new Error(task.error || task.message || 'Preparation failed')
    observeTask(task)
    if (['completed','ready'].includes(task.status) || task.already_prepared) return task
    await pause()
  }
}
async function loadProject() {
  const project = await get('/api/graph/project/' + projectId.value)
  name.value = project.name || project.project_name || name.value
  if (project.studio_settings) settings = {...settings,...project.studio_settings}
  graphId = project.graph_id || graphId
  if (graphId) await refreshGraph()
  return project
}
async function prepareProject() {
  let project = await loadProject()
  if (project.status !== 'graph_completed') {
    if (['failed','ontology_failed'].includes(project.status)) throw new Error(project.error || 'Source processing failed. Start a new simulation.')
    phase.value = 'building';progress.value = null;taskDetail.value={};lastProgressAt=Date.now()
    const build = project.status === 'graph_building' && project.graph_build_task_id ? {task_id:project.graph_build_task_id} : await post('/api/graph/build',{project_id:projectId.value})
    if (build.task_id) await waitTask('/api/graph/task/' + build.task_id)
    project = await loadProject()
  }
  if (!project.graph_id) throw new Error('No graph was produced. Check your source material.')
  graphId = project.graph_id
  if (!simulationId.value) {
    // Existing projects may already own a run; reopening must never launch a duplicate.
    const simulations = await get('/api/simulation/list',{params:{project_id:projectId.value}})
    const existing = Array.isArray(simulations) ? simulations[0] : simulations?.simulations?.[0]
    const sim = existing || await post('/api/simulation/create',{project_id:projectId.value,graph_id:graphId,enable_twitter:settings.platform !== 'reddit',enable_reddit:settings.platform !== 'twitter'})
    simulationId.value = sim.simulation_id
    remember()
  }
  await router.replace('/simulation/' + simulationId.value + '/start')
  await prepareAndRun()
}
async function prepareAndRun() {
  const sim = await get('/api/simulation/' + simulationId.value)
  projectId.value = sim.project_id
  settings.platform = sim.enable_twitter === false ? 'reddit' : sim.enable_reddit === false ? 'twitter' : settings.platform
  await loadProject()
  const run = await get('/api/simulation/' + simulationId.value + '/run-status')
  if (run.runner_status !== 'idle') { state.value = run;await monitor();return }
  phase.value = 'preparing';progress.value = null;taskDetail.value={};lastProgressAt=Date.now()
  if (sim.status === 'failed' && !sim.config_generated) prepareTask = ''
  let readiness
  try { readiness = await post('/api/simulation/prepare/status',{simulation_id:simulationId.value,...(prepareTask ? {task_id:prepareTask} : {})}) }
  catch(e) {
    if (!prepareTask || e.response?.status !== 404) throw e
    // Task records live in server memory; after a server restart the saved
    // id expires, while completed persona checkpoints remain on disk.
    prepareTask='';remember()
    readiness = await post('/api/simulation/prepare/status',{simulation_id:simulationId.value})
  }
  if (!['ready','completed'].includes(readiness.status) && !readiness.already_prepared) {
    if (!prepareTask) {
      const body={simulation_id:simulationId.value,use_llm_for_profiles:true,run_async:true}
      let prep
      try { prep=await post('/api/simulation/prepare',body,{timeout:12000}) }
      catch(e) {
        if(e.code !== 'ECONNABORTED') throw e
        // In benchmark mode the server can keep preparing after the request
        // times out. A second call attaches to its existing task.
        prep=await post('/api/simulation/prepare',body,{timeout:30000})
      }
      prepareTask=prep.task_id || '';remember()
    }
    await waitTask('/api/simulation/prepare/status',{simulation_id:simulationId.value,...(prepareTask ? {task_id:prepareTask} : {})})
  }
  phase.value = 'running';progress.value = null;taskDetail.value={};lastProgressAt=Date.now()
  state.value = await post('/api/simulation/start',{simulation_id:simulationId.value,platform:settings.platform,rounds:settings.rounds,enable_graph_memory_update:true,interactive:true})
  remember()
  await monitor()
}
async function monitor() {
  let failures = 0
  while(active) {
    const result = runProgress(state.value,settings.platform)
    if (result.failed) throw new Error(state.value.error || 'The simulation failed. Check the model connection and available resources.')
    if (result.percent !== progress.value) lastProgressAt=Date.now()
    progress.value = result.percent
    phase.value = result.complete ? 'completed' : result.stopped ? 'stopped' : 'running'
    if (result.complete || result.stopped) { await refreshGraph();return }
    await pause()
    try { state.value = await get('/api/simulation/' + simulationId.value + '/run-status');failures=0;notice.value=false } catch(e) {ensureActive();notice.value=true;if (++failures >= 5) throw e}
  }
}
async function stop() { stopping.value=true;try {await post('/api/simulation/stop',{simulation_id:simulationId.value});state.value=await get('/api/simulation/' + simulationId.value + '/run-status')}catch(e){error.value=e.response?.data?.error||e.message}finally{stopping.value=false} }
async function uploadPending() {
  const pending=getPendingUpload()
  if(!pending.isPending||!pending.files.length)throw new Error('Your documents are no longer in this tab. Return to the studio to select them again.')
  settings={...settings,...pending.settings};name.value=pending.projectName
  phase.value='uploading';progress.value=null
  const form=new FormData();pending.files.forEach(file=>form.append('files',file));form.append('simulation_requirement',pending.simulationRequirement);form.append('rounds',String(settings.rounds));form.append('platform',settings.platform);if(pending.projectName)form.append('project_name',pending.projectName)
  const res=await post('/api/graph/ontology/generate',form)
  projectId.value=res.project_id;remember();clearPendingUpload();await router.replace('/process/'+projectId.value)
}
async function resume() { if(running)return;error.value='';notice.value=false;running=true;try { if(simulationId.value) await prepareAndRun();else {if(!projectId.value)await uploadPending();await prepareProject()} }catch(e){if(active)error.value=e.response?.data?.error||e.message}finally{running=false} }
onMounted(async () => {
  graphTimer=setInterval(refreshGraph,8000)
  clockTimer=setInterval(()=>{clock.value=Date.now()},15000)
  try {
    simulationId.value=route.params.simulationId||'';projectId.value=route.params.projectId === 'new' ? '' : route.params.projectId||''
    const saved=loadWorkspace(simulationId.value||projectId.value)
    settings={...settings,...saved};prepareTask=saved.prepareTask||''
    if(!simulationId.value)simulationId.value=saved.simulationId||''
    if(!simulationId.value&&!projectId.value) {
      await uploadPending()
    }
    await resume()
  }catch(e){if(active)error.value=e.response?.data?.error||e.message}
})
onBeforeUnmount(()=>{active=false;clearInterval(graphTimer);clearInterval(clockTimer)})
</script>
<style scoped>.run-workspace{height:100dvh;min-height:520px;display:flex;flex-direction:column}.run-workspace :deep(.studio-header){flex-shrink:0}.run-workspace :deep(.header-location){max-width:50vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}</style>
