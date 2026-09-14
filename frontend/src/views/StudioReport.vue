<template>
  <div :class="['report-workspace',{generating:!complete,embedded}]">
    <StudioHeader v-if="!embedded" :label="t('report')" />
    <StudioResultNav v-if="!embedded" :simulation-id="simulationId" active="report" />
    <template v-if="!complete"><StudioGraph v-if="!embedded" :data="graph"/><div v-else class="embedded-report-wait"><span class="eyebrow">{{ t('results') }}</span><h2>{{ t('reporting') }}</h2></div><StudioProgress :title="t(error ? 'reportFailed' : 'reporting')" phase="reporting" :value="progress" :error="error"><template v-if="error"><button class="secondary-button" @click="retry">{{ t('retry') }}</button><RouterLink to="/" class="text-button">{{ t('back') }}</RouterLink></template></StudioProgress></template>
    <main v-else class="report-content"><div class="report-meta"><span class="eyebrow">{{ t('results') }}</span><span class="report-tools"><button class="text-button" :disabled="polling" @click="regenerate">{{ t('regenerateReport') }} ↻</button><button class="text-button" @click="download">{{ t('download') }} ↓</button></span></div><h1>{{ report.outline?.title || t('report') }}</h1><p v-if="report.outline?.summary" class="report-summary">{{ report.outline.summary }}</p><p class="evidence-note">{{ t('reportEvidence') }} <span v-if="durationHours">{{ t('simulatedDuration') }}: {{ durationHours }} h.</span></p><p v-if="error" class="error-message" role="alert">{{ error }} <button class="text-button" @click="retry">{{ t('retry') }}</button></p><SafeMarkdown :text="bodyMarkdown"/><div class="report-end"><p>{{ t('interviewHint') }}</p><RouterLink class="primary-button" :to="'/simulation/' + simulationId + '/interview'">{{ t('interview') }} →</RouterLink></div></main>
  </div>
</template>
<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import service from '../api'
import StudioHeader from '../studio/StudioHeader.vue'
import StudioResultNav from '../studio/StudioResultNav.vue'
import StudioGraph from '../studio/StudioGraph.vue'
import StudioProgress from '../studio/StudioProgress.vue'
import SafeMarkdown from '../studio/SafeMarkdown.vue'
import { useStudioText } from '../studio/i18n'
defineProps({ embedded: { type: Boolean, default: false } })
const { t }=useStudioText(), route=useRoute(), report=ref({}), graph=ref(null), progress=ref(null), error=ref(''), simulationId=ref(route.params.simulationId||route.query.simulation||''), reportId=ref(route.params.reportId||''), taskId=ref(route.query.task||''), durationHours=ref(null), sections=ref([])
const complete=computed(()=>report.value.status==='completed'), fallbackContent=computed(()=>sections.value.map(s=>`## ${s.title || ''}\n\n${s.content||''}`).join('\n\n'))
const bodyMarkdown=computed(()=>{
  let text=report.value.markdown_content||fallbackContent.value
  const title=report.value.outline?.title, summary=report.value.outline?.summary
  if(title && text.trimStart().startsWith('# '+title)) text=text.trimStart().slice(('# '+title).length).trimStart()
  if(summary && text.startsWith('> '+summary)) text=text.slice(('> '+summary).length).trimStart()
  return text
})
let active=true,timer,failures=0,polling=false,generationFailed=false
async function poll() {
  if(polling||!active)return
  polling=true
  const id=reportId.value
  if(!id){polling=false;return}
  try {
    const requests=[service.get('/api/report/'+id),service.get('/api/report/'+id+'/progress')]
    if(taskId.value)requests.push(service.get('/api/graph/task/'+taskId.value))
    const results=await Promise.allSettled(requests)
    if(!active||id!==reportId.value)return
    const loaded=results[0].status==='fulfilled', hasProgress=results[1].status==='fulfilled'
    const task=results[2]?.status==='fulfilled'?results[2].value.data:null
    if(task?.status==='failed'){generationFailed=true;throw new Error(task.error||t('reportFailed'))}
    if(loaded){report.value=results[0].value.data;simulationId.value=report.value.simulation_id;failures=0;if(durationHours.value===null)loadDuration()}
    if(hasProgress){const data=results[1].value.data;progress.value=data.progress??null;if(data.status==='failed'){generationFailed=true;throw new Error(data.error||data.message||t('reportFailed'))}}
    if(task){progress.value=task.progress??progress.value;failures=0}
    if(!loaded&&!hasProgress&&!task){if(++failures>5)throw new Error(t('reportFailed'));progress.value=null}
    if(report.value.status==='failed'){generationFailed=true;throw new Error(report.value.error||t('reportFailed'))}
    if(!graph.value){try{let graphId=report.value.graph_id;if(!graphId&&simulationId.value){const sim=await service.get('/api/simulation/'+simulationId.value);graphId=sim.data.graph_id}if(graphId){const res=await service.get('/api/graph/data/'+graphId);if(active)graph.value=res.data}}catch{}}
    if(complete.value){if(!report.value.markdown_content){const res=await service.get('/api/report/'+id+'/sections');sections.value=Array.isArray(res.data.sections)?res.data.sections:Object.values(res.data.sections||{})}return}
    if(active)timer=setTimeout(poll,2500)
  }catch(e){if(active)error.value=e.response?.data?.error||e.message}finally{polling=false}
}
async function retry(){
  if(polling)return
  error.value='';failures=0
  if(generationFailed&&simulationId.value){
    polling=true
    try{const res=await service.post('/api/report/generate',{simulation_id:simulationId.value,force_regenerate:true,run_async:true});generationFailed=false;report.value={};progress.value=null;reportId.value=res.data.report_id;taskId.value=res.data.task_id||''}catch(e){error.value=e.response?.data?.error||e.message}finally{polling=false}
  }
  if(!error.value)poll()
}
function download(){const blob=new Blob([report.value.markdown_content||fallbackContent.value],{type:'text/markdown;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='SAM-report.md';a.click();URL.revokeObjectURL(url)}
async function regenerate(){
  if(polling||!simulationId.value)return
  clearTimeout(timer);polling=true;error.value=''
  try{const res=await service.post('/api/report/generate',{simulation_id:simulationId.value,force_regenerate:true,run_async:true});reportId.value=res.data.report_id;taskId.value=res.data.task_id||'';report.value={};progress.value=null;generationFailed=false}
  catch(e){error.value=e.response?.data?.error||e.message}
  finally{polling=false;if(!error.value)poll()}
}
async function loadDuration(){if(!simulationId.value)return;try{const res=await service.get('/api/simulation/'+simulationId.value+'/run-status');if(active)durationHours.value=Number(res.data.total_simulation_hours)||null}catch{}}
async function openReport(){
  if(route.params.reportId){reportId.value=route.params.reportId;poll();return}
  if(!simulationId.value){error.value=t('reportFailed');return}
  try{
    loadDuration()
    // The endpoint attaches to an active task first, then reuses a completed
    // report; switching pages during generation never starts a duplicate.
    const res=await service.post('/api/report/generate',{simulation_id:simulationId.value,run_async:true})
    if(!active)return
    reportId.value=res.data.report_id;taskId.value=res.data.task_id||'';poll()
  }catch(e){if(active)error.value=e.response?.data?.error||e.message}
}
watch(()=>[route.params.reportId,route.params.simulationId],()=>{clearTimeout(timer);report.value={};sections.value=[];error.value='';failures=0;reportId.value=route.params.reportId||'';simulationId.value=route.params.simulationId||route.query.simulation||'';openReport()})
onMounted(openReport);onBeforeUnmount(()=>{active=false;clearTimeout(timer)})
</script>
<style scoped>
.report-workspace.generating{height:100dvh;min-height:500px;display:flex;flex-direction:column}.report-workspace :deep(.studio-header){flex-shrink:0}.report-content{max-width:800px;padding:58px 30px 80px;margin:auto}.report-meta{display:flex;align-items:center;justify-content:space-between;gap:15px}.report-content>h1{font-family:Georgia,serif;font-weight:400;letter-spacing:-1.3px;font-size:42px;line-height:1.25;margin:25px 0}.report-summary{font-size:18px;line-height:1.8;color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:30px;margin-bottom:18px}.evidence-note{padding:13px 16px;background:var(--soft);border-left:2px solid var(--accent);font-size:14px;line-height:1.65;color:var(--muted);margin-bottom:30px}.evidence-note span{white-space:nowrap}.report-end{margin-top:45px;padding-top:25px;border-top:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:20px}.report-end p{font-size:14px;color:var(--muted);line-height:1.7;max-width:300px}@media(max-width:700px){.report-content{padding:32px 22px}.report-content>h1{font-size:30px}.report-end{align-items:start;flex-direction:column}}
.report-tools{display:flex;gap:20px;align-items:center}@media(max-width:700px){.report-tools{gap:10px}}
.report-workspace.embedded{height:100%;min-height:0;overflow:auto;background:var(--surface-tint)}
.report-workspace.embedded.generating{height:100%;min-height:0;overflow:hidden}
.embedded .report-content{max-width:none;min-height:100%;padding:26px 30px 50px;background:var(--surface-tint)}
.embedded .report-content>h1{font-size:clamp(26px,2.5vw,36px)}
.embedded .report-summary{font-size:16px}
.embedded-report-wait{flex:1;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:18px;padding:30px;text-align:center}
.embedded-report-wait h2{font-family:Georgia,serif;font-size:29px;font-weight:400}
@media(max-width:700px){.embedded .report-content{padding:24px 20px 50px}}
</style>
