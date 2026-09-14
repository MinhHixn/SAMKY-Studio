<template>
  <div class="interview-workspace" :class="{embedded}">
    <StudioHeader v-if="!embedded" :label="t('interview')"><button v-if="envAlive" class="text-button end-session" :disabled="sending || closing" :aria-label="t(closing ? 'ending' : 'endSession')" @click="closeSession"><span class="end-session-label">{{ t(closing ? 'ending' : 'endSession') }}</span><span class="end-session-icon" aria-hidden="true">⊗</span></button></StudioHeader>
    <StudioResultNav v-if="!embedded" :simulation-id="simulationId" active="interview" />
    <main class="interview-layout">
      <aside class="people-panel"><div class="people-intro"><p class="eyebrow">{{ t('interviewEyebrow') }}</p><h1>{{ t('interviewTitle') }}</h1></div><label class="search-field"><span class="visually-hidden">{{ t('search') }}</span><input v-model="search" class="search-input" :placeholder="t('search')" type="search" /></label><button v-if="reportId" class="person-row analyst-row" :class="{active:target === 'analyst' && !groupMode}" :disabled="sending" @click="selectTarget('analyst')"><span class="avatar analyst-avatar">S</span><span><b>{{ t('analyst') }}</b><small>{{ t('analystRole') }}</small></span></button><div class="people-label"><span>{{ t('people') }} <b class="mono">{{ profiles.length }}</b></span><button class="text-button" :class="{selected:groupMode}" :disabled="sending" @click="groupMode = !groupMode">{{ t('survey') }}</button></div><p v-if="groupMode" class="field-hint group-hint">{{ t('surveyHint') }}</p><div class="people-list"><button v-for="agent in filtered" :key="agent.id" class="person-row" :class="{active:!groupMode && target === agent.id,chosen:groupMode && selectedIds.includes(agent.id)}" :disabled="sending" @click="groupMode ? toggleAgent(agent.id) : selectTarget(agent.id)"><span class="avatar" :style="{'--avatar-color':avatarColor(agent.id)}">{{ initials(agent) }}</span><span><b>{{ agent.name || agent.username }}</b><small>{{ agent.profession || agent.entity_type || agent.country }}</small></span><span v-if="groupMode" class="selection-box" :aria-label="selectedIds.includes(agent.id) ? t('selectedCount') : ''">{{ selectedIds.includes(agent.id) ? '✓' : '+' }}</span></button><p v-if="!filtered.length" class="empty-state">{{ t(loading ? 'checking' : profiles.length ? 'noMatches' : 'noAgents') }}</p></div></aside>
      <section class="conversation-panel"><header class="conversation-header"><div class="conversation-person"><span class="avatar" :style="{'--avatar-color':avatarColor(target)}">{{ groupMode ? '◎' : target === 'analyst' ? 'S' : initials(currentAgent) }}</span><div><h2>{{ groupMode ? t('survey') : targetName }}</h2><p>{{ groupMode ? selectedIds.length + ' ' + t('selectedCount') : target === 'analyst' ? t('analystRole') : currentAgent?.profession || t('interview') }}</p></div></div><button class="text-button export-button" :disabled="!messages.length" @click="exportChat">{{ t('export') }} ↓</button></header>
        <details v-if="!groupMode && target !== 'analyst' && currentAgent" class="agent-profile"><summary>{{ t('profile') }}</summary><p>{{ currentAgent.bio || currentAgent.description || currentAgent.persona }}</p></details>
        <div ref="messagesElement" class="messages-area" role="log" aria-live="polite" :aria-label="t('interview')"><div v-if="!messages.length" class="conversation-empty"><span class="conversation-glyph">“</span><h3>{{ t('startChat') }}</h3><p>{{ t('interviewHint') }}</p><div class="starter-prompts"><button v-for="key in ['prompt1','prompt2','prompt3']" :key="key" type="button" :disabled="!canAsk" @click="input=t(key);composer?.focus()">{{ t(key) }} <span>↗</span></button></div></div><article v-for="(message,index) in messages" :key="index" class="message" :class="message.role"><span class="message-author">{{ message.role === 'user' ? t('you') : message.name || targetName }}<time v-if="message.time">{{ formatTime(message.time) }}</time></span><SafeMarkdown :text="message.content" /></article><div v-if="sending" class="thinking" role="status"><span>● ● ●</span> {{ t('thinking') }}</div></div>
        <div class="composer-area"><p v-if="error" class="error-message" role="alert">{{ error }} <button v-if="!sending" class="text-button" @click="checkEnv">{{ t('retry') }}</button></p><p v-if="(groupMode || target !== 'analyst') && !envAlive" class="env-notice" role="status">{{ t(!envChecked ? 'envChecking' : archivedAvailable && !groupMode ? 'archivedInterview' : 'envClosed') }}</p><form class="composer" @submit.prevent="send"><textarea ref="composer" v-model="input" :disabled="!canAsk || sending" :placeholder="t('ask')" :aria-label="t('ask')" rows="2" maxlength="8000" @keydown.enter.exact="sendOnEnter"/><button class="send-button" :disabled="!canAsk || sending || !input.trim() || (groupMode && !selectedIds.length)" :aria-label="t('send')" type="submit">↑</button></form><div class="composer-foot"><span>SAMKY Studio</span><span>Enter ↵ <span class="muted">· Shift + Enter</span></span></div></div>
      </section>
    </main>
  </div>
</template>
<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import service from '../api'
import StudioHeader from '../studio/StudioHeader.vue'
import StudioResultNav from '../studio/StudioResultNav.vue'
import SafeMarkdown from '../studio/SafeMarkdown.vue'
import { useStudioText } from '../studio/i18n'
import { getReportReply } from '../utils/reportResponse'
defineProps({ embedded: { type: Boolean, default: false } })
const { t, locale }=useStudioText(),route=useRoute()
const simulationId=ref(route.params.simulationId||''),reportId=ref(route.params.reportId||''),profiles=ref([]),target=ref(null),groupMode=ref(false),selectedIds=ref([]),search=ref(''),input=ref(''),error=ref(''),sending=ref(false),loading=ref(true),envAlive=ref(false),archivedAvailable=ref(false),envChecked=ref(false),closing=ref(false),history=ref({}),messagesElement=ref(null),composer=ref(null)
let active=true,envTimer,platform='reddit'
const filtered=computed(()=>profiles.value.filter(p=>`${p.name} ${p.username} ${p.profession}`.toLowerCase().includes(search.value.toLowerCase())))
const currentAgent=computed(()=>profiles.value.find(p=>p.id===target.value)),targetName=computed(()=>target.value==='analyst'?t('analyst'):currentAgent.value?.name||currentAgent.value?.username||t('interview'))
const historyKey=computed(()=>groupMode.value?'group':String(target.value)),messages=computed(()=>history.value[historyKey.value]||[])
const canAsk=computed(()=>!loading.value&&!closing.value&&(groupMode.value?envAlive.value:target.value==='analyst'?!!reportId.value:(envAlive.value||archivedAvailable.value)&&target.value!==null))
function initials(agent){return (agent?.name||agent?.username||'?').split(/\s+/).slice(0,2).map(s=>s[0]).join('').toUpperCase()}
function avatarColor(id){return ['#e8eee0','#e2ece8','#f0e9dc','#e3e9ef','#eee5e3'][Math.abs(Number(id)||0)%5]}
function selectTarget(id){if(sending.value)return;target.value=id;groupMode.value=false;error.value='';input.value=''}
function toggleAgent(id){selectedIds.value=selectedIds.value.includes(id)?selectedIds.value.filter(v=>v!==id):[...selectedIds.value,id]}
function persist(){try{sessionStorage.setItem('sam:interview:'+simulationId.value,JSON.stringify(history.value))}catch{}}
function formatTime(value){return new Date(value).toLocaleTimeString(locale.value,{hour:'2-digit',minute:'2-digit'})}
function scroll(){nextTick(()=>{if(messagesElement.value)messagesElement.value.scrollTop=messagesElement.value.scrollHeight})}
watch(()=>messages.value.length,scroll)
async function checkEnv(){if(!simulationId.value)return;try{const res=await service.post('/api/simulation/env-status',{simulation_id:simulationId.value});if(active){envAlive.value=!!res.data.env_alive;archivedAvailable.value=!!res.data.archived_available;envChecked.value=true}}catch(e){if(active){envAlive.value=false;error.value=e.response?.data?.error||e.message}}}
async function closeSession(){closing.value=true;try{await service.post('/api/simulation/close-env',{simulation_id:simulationId.value,timeout:10});envAlive.value=false;envChecked.value=true}catch(e){error.value=e.response?.data?.error||e.message}finally{closing.value=false}}
function sendOnEnter(event){if(event.isComposing)return;event.preventDefault();send()}
async function send(){
  if(sending.value||!canAsk.value||!input.value.trim()||(groupMode.value&&!selectedIds.value.length))return
  const question=input.value.trim(),key=historyKey.value,isGroup=groupMode.value,recipient=target.value,ids=isGroup?[...selectedIds.value]:[recipient],previous=[...(history.value[key]||[])].slice(-6)
  history.value[key]=[...(history.value[key]||[]),{role:'user',content:question,time:new Date().toISOString()}];persist();input.value='';sending.value=true;error.value='';scroll()
  try{
    if(recipient==='analyst'&&!isGroup){const res=await service.post('/api/report/chat',{simulation_id:simulationId.value,message:question,chat_history:previous.map(m=>({role:m.role,content:m.content}))},{timeout:120000});history.value[key].push({role:'assistant',name:t('analyst'),content:getReportReply(res.data),time:new Date().toISOString()})}
    else if (!isGroup) {
      const prompt=previous.length?`Previous conversation:\n${previous.map(m=>`${m.role}: ${m.content}`).join('\n')}\n\nQuestion: ${question}`:question
      const endpoint=envAlive.value?'/api/simulation/interview':'/api/simulation/interview/archived'
      const res=await service.post(endpoint,{simulation_id:simulationId.value,platform,agent_id:recipient,prompt,timeout:120},{timeout:135000})
      const reply=res.data?.result||{},content=reply.response||reply.answer
      if(!res.data?.success||typeof content!=='string'||!content.trim())throw new Error(res.data?.error||'No reply was returned.')
      history.value[key].push({role:'assistant',name:targetName.value,content,time:new Date().toISOString()})
    } else {
      const prompt=!isGroup&&previous.length?`Previous conversation:\n${previous.map(m=>`${m.role}: ${m.content}`).join('\n')}\n\nQuestion: ${question}`:question
      // No retry for a mutating conversation request: a timeout may still be running.
      const res=await service.post('/api/simulation/interview/batch',{simulation_id:simulationId.value,platform,interviews:ids.map(id=>({agent_id:id,prompt,platform})),timeout:120},{timeout:135000})
      const body=res.data.result||res.data,results=body.results||{},replies=Array.isArray(results)?results:Object.values(results)
      for(const id of ids){const reply=results[`${platform}_${id}`]||replies.find(r=>Number(r.agent_id)===Number(id));const content=reply?.response||reply?.answer;const person=profiles.value.find(p=>p.id===id);if(typeof content!=='string'||!content.trim()){error.value=`${person?.name||id}: ${reply?.error||'No reply was returned.'}`;continue}history.value[key].push({role:'assistant',name:person?.name||person?.username,content,time:new Date().toISOString()})}
    }
  }catch(e){if(active){error.value=e.response?.data?.error||e.message;input.value=question;checkEnv()}}finally{persist();if(active){sending.value=false;scroll();nextTick(()=>composer.value?.focus())}}
}
function exportChat(){const text=messages.value.map(m=>`## ${m.role==='user'?t('you'):m.name||targetName.value}\n\n${m.content}`).join('\n\n');const url=URL.createObjectURL(new Blob([text],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='SAM-interview.md';a.click();URL.revokeObjectURL(url)}
onMounted(async()=>{
  try{
    if(reportId.value){const res=await service.get('/api/report/'+reportId.value);simulationId.value=res.data.simulation_id}
    if(!simulationId.value)throw new Error('No simulation is associated with this interview.')
    const sim=await service.get('/api/simulation/'+simulationId.value);platform=sim.data.enable_reddit===false?'twitter':'reddit'
    if(!reportId.value){try{const res=await service.get('/api/report/by-simulation/'+simulationId.value);reportId.value=res.data.report_id}catch(e){if(e.response?.status!==404)throw e}}
    const res=await service.get('/api/simulation/'+simulationId.value+'/profiles/realtime',{params:{platform}})
    if(!active)return
    profiles.value=(res.data.profiles||[]).map((p,index)=>({...p,id:Number(p.user_id??p.agent_id??index)}));target.value=profiles.value[0]?.id??(reportId.value?'analyst':null)
    try{history.value=JSON.parse(sessionStorage.getItem('sam:interview:'+simulationId.value)||'{}')}catch{history.value={}}
    await checkEnv();envTimer=setInterval(checkEnv,15000)
  }catch(e){if(active)error.value=e.response?.data?.error||e.message}finally{if(active)loading.value=false}
})
onBeforeUnmount(()=>{active=false;clearInterval(envTimer)})
</script>
<style scoped>
.end-session-icon{display:none}.interview-workspace{height:100dvh;min-height:550px;display:flex;flex-direction:column}.interview-workspace :deep(.studio-header){flex-shrink:0}.interview-layout{display:grid;grid-template-columns:330px minmax(0,1fr);flex:1;min-height:0;max-width:1400px;width:100%;margin:0 auto;padding:0 30px}.people-panel{padding:34px 26px 0 0;border-right:1px solid var(--line);min-height:0;display:flex;flex-direction:column}.people-intro .eyebrow{font-size:12px;letter-spacing:1.5px}.people-intro h1{font-size:27px;font-weight:450;line-height:1.3;letter-spacing:-1px;margin:15px 0 26px}.search-field{margin-bottom:15px}.search-input{font-size:14px;padding:11px;background:transparent}.people-label{display:flex;align-items:center;justify-content:space-between;margin:19px 0 12px;font-size:12px;color:var(--muted)}.people-label b{font-weight:400;margin-left:5px}.people-label button{font-size:12px;padding:0}.people-label button.selected{color:var(--accent)}.people-list{overflow:auto;min-height:0;padding-bottom:20px}.person-row{width:100%;display:flex;align-items:center;gap:12px;padding:12px 10px;border:1px solid transparent;background:transparent;border-radius:7px;text-align:left;margin-bottom:4px}.person-row:hover{background:var(--soft)}.person-row.active,.person-row.chosen{background:var(--soft);border-color:var(--line)}.person-row>span:nth-child(2){display:grid;gap:5px;min-width:0;flex:1}.person-row b{font-size:14px;font-weight:550;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.person-row small{font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.avatar{width:36px;height:36px;border-radius:50%;display:grid;place-items:center;flex-shrink:0;background:var(--avatar-color,#e3eade);font-family:Georgia,serif;font-size:14px;color:#4f6855}.analyst-avatar{background:var(--accent);color:white;font:600 13px Inter,sans-serif}.analyst-row{border:1px solid var(--line);margin-top:5px}.selection-box{color:var(--accent);font-size:18px}.group-hint{font-size:12px;margin-bottom:10px}.conversation-panel{margin:24px 0 24px 28px;background:var(--surface);border:1px solid var(--line);border-radius:10px;display:flex;flex-direction:column;min-height:0;overflow:hidden}.conversation-header{padding:20px 25px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:15px;align-items:center}.conversation-person{display:flex;align-items:center;gap:12px;min-width:0}.conversation-person>div{min-width:0}.conversation-person h2{font-size:16px;font-weight:550;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.conversation-person p{font-size:12px;color:var(--muted);margin-top:6px}.export-button{font-size:12px;white-space:nowrap}.agent-profile{padding:12px 25px;border-bottom:1px solid var(--line);font-size:12px;color:var(--muted)}.agent-profile summary{cursor:pointer}.agent-profile p{padding-top:12px;line-height:1.8;max-height:140px;overflow:auto;font-size:14px;white-space:pre-wrap}.messages-area{flex:1;overflow:auto;min-height:0;padding:28px 36px;scroll-behavior:smooth}.conversation-empty{min-height:100%;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;max-width:410px;margin:auto;padding:15px 0}.conversation-glyph{font:80px Georgia,serif;line-height:.9;color:var(--accent)}.conversation-empty h3{font-family:Georgia,serif;font-size:25px;letter-spacing:-.6px;font-weight:400;line-height:1.3;margin:12px 0}.conversation-empty>p{font-size:14px;color:var(--muted);line-height:1.8;max-width:330px}.starter-prompts{display:grid;gap:8px;width:100%;margin-top:26px}.starter-prompts button{display:flex;align-items:center;justify-content:space-between;text-align:left;font-size:14px;gap:15px;padding:13px 15px;border:1px solid var(--line);border-radius:6px;background:var(--input)}.starter-prompts button:hover{border-color:var(--accent);background:var(--soft)}.starter-prompts span{color:var(--accent)}.message{margin-bottom:24px;max-width:650px}.message.user{margin-left:auto;background:var(--soft);padding:16px 20px;border-radius:8px;max-width:90%}.message-author{display:flex;align-items:center;gap:14px;font-size:12px;font-weight:600;margin-bottom:8px;color:var(--accent)}.message-author time{font-weight:400;font-size:12px;color:var(--muted)}.message :deep(.prose){font-size:16px;line-height:1.8}.message :deep(p:last-child){margin-bottom:0}.thinking{font-size:14px;color:var(--muted);display:flex;align-items:center;gap:10px}.thinking span{font-size:12px;letter-spacing:3px;color:var(--accent)}.composer-area{padding:0 25px 17px}.composer-area .error-message{margin-bottom:10px;font-size:14px}.env-notice{font-size:14px;line-height:1.6;color:var(--muted);padding:10px 0}.composer{display:flex;align-items:flex-end;gap:10px;border:1px solid var(--line);border-radius:8px;padding:10px;background:var(--input)}.composer:focus-within{border-color:var(--accent)}.composer textarea{width:100%;resize:none;background:transparent;border:0;padding:8px;font-size:16px;line-height:1.7;outline:none}.send-button{width:36px;height:36px;flex-shrink:0;border:0;background:var(--accent);color:white;border-radius:6px;font-size:22px}.composer-foot{display:flex;justify-content:space-between;padding:11px 2px 0;font-size:12px;color:var(--muted)}
@media(max-width:1000px){.interview-layout{grid-template-columns:270px minmax(0,1fr);padding:0 20px}.people-panel{padding-right:18px}.conversation-panel{margin-left:18px}.people-intro h1{font-size:24px}.messages-area{padding:20px}.export-button{display:none}.conversation-header{padding:17px}.composer-area{padding:0 17px 15px}}
@media(max-width:700px){.interview-workspace{height:auto;min-height:100dvh}.interview-layout{display:flex;flex-direction:column;padding:0 20px}.people-panel{border:0;padding:24px 0 0}.people-intro h1{font-size:24px;margin:12px 0 18px}.people-list{display:flex;overflow:auto;gap:5px;max-height:160px;padding:0 0 8px}.person-row{min-width:155px;width:auto}.person-row>span:nth-child(2){max-width:130px}.people-label{margin:12px 0}.people-intro .eyebrow{display:none}.analyst-row{width:100%;margin:0}.conversation-panel{margin:12px 0 22px;min-height:550px;height:72dvh}.messages-area{padding:18px}.conversation-empty h3{font-size:22px}.starter-prompts button{font-size:12px}.composer textarea{font-size:18px}.end-session-label{display:none}.end-session-icon{display:inline;font-size:20px}.search-input{font-size:18px}.conversation-header{padding:14px}.message.user{max-width:95%}.header-end .text-button{font-size:12px}}
.interview-workspace.embedded{height:100%;min-height:0;background:var(--surface-tint)}
.embedded .interview-layout{display:flex;flex-direction:column;min-height:0;max-width:none;padding:0 12px}
.embedded .people-panel{border:0;flex-shrink:0;padding:12px 0 0}
.embedded .people-intro{display:none}
.embedded .search-field{margin-bottom:8px}
.embedded .search-input{padding:8px 11px;font-size:14px}
.embedded .analyst-row{margin:0 0 6px;max-height:56px}
.embedded .people-label{margin:6px 0;font-size:12px}
.embedded .people-list{display:flex;flex-shrink:0;gap:5px;min-height:0;max-height:68px;overflow:auto;padding:0 0 6px}
.embedded .person-row{min-width:145px;width:auto;padding:8px;margin:0}
.embedded .person-row>span:nth-child(2){max-width:120px}
.embedded .conversation-panel{flex:1;min-height:280px;height:auto;margin:6px 0 12px}
.embedded .messages-area{padding:16px}
.embedded .conversation-empty h3{font-size:22px}
.embedded .starter-prompts{margin-top:16px}
.embedded .starter-prompts button{padding:10px 12px;font-size:13px}
.embedded .composer-area{padding:0 12px 12px}
.embedded .conversation-header{padding:12px}
</style>
