<template>
  <main class="studio-shell">
    <nav class="topbar" :aria-label="t('nav')">
      <button class="brand" type="button" :aria-label="t('home')">
        <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>
        <span>SAM <b>Studio</b></span>
      </button>
      <div class="topbar-actions">
        <div class="locale-switch" aria-label="Language">
          <button v-for="item in languages" :key="item.code" type="button" :class="{ active: locale === item.code }" @click="locale = item.code">{{ item.label }}</button>
        </div>
        <a class="text-link" href="#headless">{{ t('noUi') }}</a>
        <a class="github-link" href="https://github.com/nikmcfly/MiroFish-Offline" target="_blank" rel="noreferrer">
          {{ t('github') }}
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7M8 7h9v9" /></svg>
        </a>
      </div>
    </nav>

    <section class="workspace" aria-labelledby="page-title">
      <div class="intro">
        <div class="eyebrow"><span></span> {{ t('eyebrow') }}</div>
        <h1 id="page-title">{{ t('titleA') }}<br><em>{{ t('titleB') }}</em></h1>
        <p class="intro-copy">{{ t('intro') }}</p>

        <div class="runtime-card" :class="runtimeClass" aria-live="polite">
          <div class="runtime-head">
            <span class="pulse" aria-hidden="true"></span>
            <div>
              <small>{{ t('environment') }}</small>
              <strong>{{ runtimeTitle }}</strong>
            </div>
            <button type="button" class="refresh" :disabled="checking" @click="loadStatus" :aria-label="t('refresh')">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5M6.1 9A7 7 0 0 1 18 6l2 6M17.9 15A7 7 0 0 1 6 18l-2-6" /></svg>
            </button>
          </div>
          <div class="runtime-grid">
            <div><span>{{ t('model') }}</span><b>{{ runtime.model || t('checking') }}</b></div>
            <div><span>{{ t('neo4j') }}</span><b>{{ neo4jLabel }}</b></div>
            <div><span>{{ t('mode') }}</span><b>{{ runtime.mode === 'online' ? t('online') : t('offline') }}</b></div>
          </div>
          <p v-if="runtimeMessage" class="runtime-message">{{ runtimeMessage }}</p>
        </div>

        <ol class="mini-flow" :aria-label="t('flowLabel')">
          <li><span>01</span><div><b>{{ t('flow1') }}</b><small>{{ t('flow1b') }}</small></div></li>
          <li><span>02</span><div><b>{{ t('flow2') }}</b><small>{{ t('flow2b') }}</small></div></li>
          <li><span>03</span><div><b>{{ t('flow3') }}</b><small>{{ t('flow3b') }}</small></div></li>
        </ol>
      </div>

      <section class="event-panel" aria-labelledby="new-event-title">
        <header class="panel-header">
          <div>
            <span class="step-label">{{ t('newEvent') }}</span>
            <h2 id="new-event-title">{{ t('create') }}</h2>
          </div>
          <span class="privacy-badge">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 5 6v5c0 4.6 2.8 8.5 7 10 4.2-1.5 7-5.4 7-10V6l-7-3Z" /></svg>
            {{ t('privacy') }}
          </span>
        </header>

        <form @submit.prevent="startSimulation">
          <label class="field">
            <span>{{ t('eventName') }} <small>{{ t('optional') }}</small></span>
            <input v-model="projectName" type="text" maxlength="90" :placeholder="t('eventPlaceholder')" :disabled="loading" />
          </label>

          <label class="field">
            <span>{{ t('question') }}</span>
            <textarea v-model="simulationRequirement" rows="5" maxlength="2400" :disabled="loading" :placeholder="t('questionPlaceholder')"></textarea>
            <small class="counter">{{ simulationRequirement.length }} / 2400</small>
          </label>

          <div class="field">
            <span>{{ t('sources') }}</span>
            <div
              class="dropzone"
              :class="{ active: isDragOver, filled: files.length }"
              role="button"
              tabindex="0"
              @click="triggerFileInput"
              @keydown.enter.prevent="triggerFileInput"
              @keydown.space.prevent="triggerFileInput"
              @dragover.prevent="isDragOver = true"
              @dragleave.prevent="isDragOver = false"
              @drop.prevent="handleDrop"
            >
              <input ref="fileInput" hidden type="file" multiple accept=".pdf,.md,.markdown,.txt" @change="handleFileSelect" :disabled="loading" />
              <div v-if="!files.length" class="drop-empty">
                <span class="upload-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7 9m5-5 5 5M5 15v4h14v-4" /></svg></span>
                <div><b>{{ t('drop') }}</b><small>{{ t('browse') }}</small></div>
              </div>
              <div v-else class="file-stack">
                <div v-for="(file, index) in files" :key="`${file.name}-${file.size}`" class="file-row">
                  <span class="file-type">{{ fileExtension(file.name) }}</span>
                  <div><b>{{ file.name }}</b><small>{{ formatBytes(file.size) }}</small></div>
                  <button type="button" @click.stop="removeFile(index)" :aria-label="`${t('remove')} ${file.name}`">×</button>
                </div>
                <button type="button" class="add-more" @click.stop="triggerFileInput">{{ t('add') }}</button>
              </div>
            </div>
            <p v-if="fileError" class="form-error" role="alert">{{ fileError }}</p>
          </div>

          <div class="launch-row">
            <div class="launch-note">
              <span>{{ files.length || 0 }} {{ t('documents') }}</span>
              <span>•</span>
              <span>{{ t('nextSetup') }}</span>
            </div>
            <button class="launch-button" type="submit" :disabled="!canSubmit || loading">
              <span>{{ loading ? t('opening') : t('launch') }}</span>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
            </button>
          </div>
        </form>
      </section>
    </section>

    <section id="headless" class="headless-strip">
      <div>
        <span class="terminal-dot"></span>
        <div><b>{{ t('headlessTitle') }}</b><small>{{ t('headlessBody') }}</small></div>
      </div>
      <code>python backend/scripts/sam_cli.py run --file event.pdf --goal "..." --wait</code>
      <button type="button" @click="copyCommand">{{ copied ? t('copied') : t('copy') }}</button>
    </section>

    <section class="history-wrap">
      <HistoryDatabase />
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import HistoryDatabase from '../components/HistoryDatabase.vue'
import { getSystemStatus } from '../api/system'
import { setPendingUpload } from '../store/pendingUpload'
import { useI18n } from '../i18n'

const router = useRouter()
const { locale, t } = useI18n()
const languages = [{ code: 'en', label: 'EN' }, { code: 'vi', label: 'VI' }, { code: 'es', label: 'ES' }]
const fileInput = ref(null)
const files = ref([])
const projectName = ref(localStorage.getItem('mirofish:draft:name') || '')
const simulationRequirement = ref(localStorage.getItem('mirofish:draft:goal') || '')
const fileError = ref('')
const isDragOver = ref(false)
const loading = ref(false)
const checking = ref(false)
const copied = ref(false)
const runtime = ref({ mode: 'offline', model: '', reachable: false, neo4j: false, checked: false })

const canSubmit = computed(() => simulationRequirement.value.trim().length >= 12 && files.value.length > 0)
const runtimeClass = computed(() => ({ ready: runtime.value.reachable && runtime.value.neo4j, degraded: runtime.value.checked && (!runtime.value.reachable || !runtime.value.neo4j) }))
const runtimeTitle = computed(() => {
  if (!runtime.value.checked) return t('checking')
  if (runtime.value.reachable && runtime.value.neo4j) return t('ready')
  return t('setup')
})
const neo4jLabel = computed(() => runtime.value.checked ? (runtime.value.neo4j ? t('connected') : t('disconnected')) : t('checking'))
const runtimeMessage = computed(() => {
  if (!runtime.value.checked || (runtime.value.reachable && runtime.value.neo4j)) return ''
  if (!runtime.value.reachable && !runtime.value.neo4j) return t('bothDown')
  return runtime.value.reachable ? t('neoDown') : t('modelDown')
})

watch(projectName, value => localStorage.setItem('mirofish:draft:name', value))
watch(simulationRequirement, value => localStorage.setItem('mirofish:draft:goal', value))

async function loadStatus() {
  checking.value = true
  try {
    const response = await getSystemStatus()
    const data = response.data || {}
    const service = data.runtime || data.ollama || {}
    runtime.value = {
      mode: service.mode || 'offline',
      model: service.model || service.model_configured || '',
      reachable: Boolean(service.reachable),
      neo4j: Boolean(data.neo4j?.connected),
      checked: true
    }
  } catch {
    runtime.value = { ...runtime.value, checked: true, reachable: false, neo4j: false }
  } finally {
    checking.value = false
  }
}

function triggerFileInput() { if (!loading.value) fileInput.value?.click() }
function handleFileSelect(event) { addFiles(Array.from(event.target.files || [])); event.target.value = '' }
function handleDrop(event) { isDragOver.value = false; addFiles(Array.from(event.dataTransfer?.files || [])) }
function addFiles(incoming) {
  const allowed = ['PDF', 'MD', 'MARKDOWN', 'TXT']
  const accepted = incoming.filter(file => allowed.includes(fileExtension(file.name)) && file.size <= 50 * 1024 * 1024)
  fileError.value = accepted.length === incoming.length ? '' : t('invalidFile')
  const seen = new Set(files.value.map(file => `${file.name}:${file.size}`))
  files.value.push(...accepted.filter(file => !seen.has(`${file.name}:${file.size}`)))
}
function removeFile(index) { files.value.splice(index, 1) }
function fileExtension(name) { return name.split('.').pop()?.toUpperCase() || 'FILE' }
function formatBytes(bytes) { return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB` }

async function startSimulation() {
  if (!canSubmit.value || loading.value) return
  loading.value = true
  setPendingUpload(files.value, simulationRequirement.value.trim(), projectName.value.trim())
  await router.push({ name: 'Process', params: { projectId: 'new' } })
  loading.value = false
}

async function copyCommand() {
  const command = 'python backend/scripts/sam_cli.py run --file event.pdf --goal "..." --wait'
  try { await navigator.clipboard.writeText(command); copied.value = true; setTimeout(() => { copied.value = false }, 1600) } catch { copied.value = false }
}

onMounted(loadStatus)
</script>

<style scoped>
.studio-shell { --ink:#f4f5f8; --muted:#9aa3b5; --line:rgba(255,255,255,.1); --accent:#ff7741; min-height:100vh; color:var(--ink); background:radial-gradient(circle at 15% 18%,rgba(56,96,150,.18),transparent 27rem),radial-gradient(circle at 88% 72%,rgba(255,119,65,.09),transparent 26rem),#080b12; overflow:hidden; }
.studio-shell::before { content:""; position:fixed; inset:0; pointer-events:none; opacity:.32; background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px); background-size:54px 54px; mask-image:linear-gradient(to bottom,black,transparent 82%); }
.topbar { height:76px; max-width:1500px; margin:0 auto; padding:0 42px; display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid var(--line); position:relative; z-index:2; }
.brand { color:var(--ink); background:none; border:0; padding:0; display:flex; align-items:center; gap:12px; font-size:1.05rem; letter-spacing:-.02em; cursor:pointer; }.brand b{color:#aeb7c8;font-weight:500}.brand-mark{width:28px;height:28px;display:grid;grid-template-columns:repeat(3,1fr);gap:3px;align-items:end}.brand-mark i{display:block;border-radius:5px 5px 2px 2px;background:var(--accent)}.brand-mark i:nth-child(1){height:44%;opacity:.55}.brand-mark i:nth-child(2){height:100%}.brand-mark i:nth-child(3){height:68%;opacity:.8}
.topbar-actions{display:flex;align-items:center;gap:26px}.text-link,.github-link{color:#bdc5d4;text-decoration:none;font-size:.9rem}.github-link{display:inline-flex;align-items:center;gap:8px;padding:9px 14px;border:1px solid var(--line);border-radius:10px;background:rgba(255,255,255,.025)}.github-link svg{width:16px;fill:none;stroke:currentColor;stroke-width:1.8}.text-link:hover,.github-link:hover{color:#fff;border-color:rgba(255,255,255,.24)}
.locale-switch{display:flex!important;gap:2px!important;padding:3px;border:1px solid var(--line);border-radius:9px;background:rgba(255,255,255,.025)}.locale-switch button{min-width:31px;padding:5px 6px;border:0;border-radius:6px;color:#707b8d;background:transparent;font-size:.66rem;font-weight:700;cursor:pointer}.locale-switch button:hover{color:#dce1e9}.locale-switch button.active{color:#11141b;background:#f0f2f6}
.workspace{max-width:1500px;margin:0 auto;padding:68px 42px 54px;display:grid;grid-template-columns:minmax(340px,.82fr) minmax(560px,1.18fr);gap:clamp(48px,6vw,104px);align-items:start;position:relative;z-index:1}.intro{padding-top:18px}.eyebrow{display:flex;align-items:center;gap:10px;color:#aab3c4;text-transform:uppercase;letter-spacing:.13em;font-size:.74rem;font-weight:700}.eyebrow span{width:28px;height:1px;background:var(--accent);box-shadow:0 0 12px var(--accent)}
h1{margin:24px 0 22px;font-size:clamp(3.2rem,5.2vw,6rem);line-height:.98;letter-spacing:-.065em;font-weight:570}h1 em{color:#8e99aa;font-style:normal;font-weight:430}.intro-copy{max-width:600px;margin:0 0 34px;color:#abb3c2;font-size:1.04rem;line-height:1.75}
.runtime-card{max-width:600px;padding:19px 20px 16px;border:1px solid var(--line);background:rgba(15,20,30,.64);border-radius:16px;backdrop-filter:blur(18px)}.runtime-card.ready{border-color:rgba(94,210,166,.25)}.runtime-card.degraded{border-color:rgba(255,119,65,.28)}.runtime-head{display:flex;align-items:center;gap:12px}.pulse{width:9px;height:9px;border-radius:50%;background:#8d96a6;box-shadow:0 0 0 5px rgba(141,150,166,.09)}.ready .pulse{background:#5ed2a6;box-shadow:0 0 0 5px rgba(94,210,166,.1)}.degraded .pulse{background:var(--accent);box-shadow:0 0 0 5px rgba(255,119,65,.1)}.runtime-head div{display:grid;gap:3px}.runtime-head small{color:#747f91;font-size:.66rem;letter-spacing:.13em}.runtime-head strong{font-size:.96rem;font-weight:590}.refresh{margin-left:auto;width:34px;height:34px;display:grid;place-items:center;border:0;color:#8e99aa;background:transparent;border-radius:8px;cursor:pointer}.refresh:hover{color:#fff;background:rgba(255,255,255,.06)}.refresh:disabled{opacity:.35}.refresh svg{width:17px;fill:none;stroke:currentColor;stroke-width:1.7}.runtime-grid{margin-top:17px;padding-top:15px;border-top:1px solid var(--line);display:grid;grid-template-columns:1.4fr 1fr .7fr;gap:16px}.runtime-grid div{min-width:0;display:grid;gap:4px}.runtime-grid span{color:#737d8f;font-size:.72rem}.runtime-grid b{font-size:.8rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:550}.runtime-message{margin:13px 0 0;color:#d49b83;font-size:.8rem;line-height:1.45}
.mini-flow{max-width:600px;margin:34px 0 0;padding:0;display:grid;gap:14px;list-style:none}.mini-flow li{display:flex;gap:14px;align-items:center}.mini-flow li>span{width:34px;color:#5f6a7d;font:600 .72rem ui-monospace,monospace}.mini-flow div{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:baseline}.mini-flow b{font-size:.88rem;font-weight:580}.mini-flow small{color:#727d90;font-size:.78rem}
.event-panel{border:1px solid rgba(255,255,255,.12);border-radius:22px;background:linear-gradient(145deg,rgba(26,32,46,.94),rgba(14,18,28,.97));box-shadow:0 32px 90px rgba(0,0,0,.34);overflow:hidden}.panel-header{padding:25px 28px 22px;display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1px solid var(--line)}.step-label{color:#7d8798;font:600 .68rem ui-monospace,monospace;letter-spacing:.11em}.panel-header h2{margin:8px 0 0;font-size:1.35rem;letter-spacing:-.025em;font-weight:590}.privacy-badge{display:inline-flex;align-items:center;gap:7px;padding:7px 9px;border-radius:8px;color:#9fa9ba;background:rgba(255,255,255,.04);font-size:.72rem}.privacy-badge svg{width:15px;fill:none;stroke:currentColor;stroke-width:1.5}
form{padding:25px 28px 28px;display:grid;gap:22px}.field{display:grid;gap:9px;position:relative}.field>span{color:#d8dce5;font-size:.82rem;font-weight:560}.field>span small{margin-left:7px;color:#657084;font-weight:450}input,textarea{width:100%;border:1px solid rgba(255,255,255,.105);color:#f5f6fa;background:rgba(4,7,12,.38);border-radius:11px;padding:13px 14px;font-size:.94rem;transition:border-color .2s,background .2s}textarea{min-height:120px;resize:vertical;line-height:1.6;padding-bottom:30px}input::placeholder,textarea::placeholder{color:#5f6a7c}input:hover,textarea:hover{border-color:rgba(255,255,255,.19)}input:focus,textarea:focus{border-color:rgba(255,119,65,.65);background:rgba(4,7,12,.62);outline:none}.counter{position:absolute;bottom:10px;right:12px;color:#576274;font:.68rem ui-monospace,monospace}
.dropzone{min-height:128px;border:1px dashed rgba(255,255,255,.17);border-radius:12px;display:grid;place-items:center;padding:16px;background:rgba(4,7,12,.25);cursor:pointer;transition:.2s ease}.dropzone:hover,.dropzone.active{border-color:var(--accent);background:rgba(255,119,65,.035)}.dropzone.filled{place-items:stretch}.drop-empty{display:flex;align-items:center;gap:14px}.drop-empty>div{display:grid;gap:5px}.drop-empty b{font-size:.86rem;font-weight:560}.drop-empty small{color:#6f7a8d;font-size:.74rem}.upload-icon{width:40px;height:40px;display:grid;place-items:center;border-radius:11px;color:#f09870;background:rgba(255,119,65,.1)}.upload-icon svg{width:19px;fill:none;stroke:currentColor;stroke-width:1.7}.file-stack{display:grid;gap:8px}.file-row{min-width:0;display:grid;grid-template-columns:38px 1fr 30px;gap:10px;align-items:center;padding:8px;border-radius:9px;background:rgba(255,255,255,.035)}.file-type{color:#ff9a70;font:700 .62rem ui-monospace,monospace}.file-row div{min-width:0;display:grid;gap:3px}.file-row b{overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-size:.78rem;font-weight:520}.file-row small{color:#657084;font-size:.66rem}.file-row button{border:0;background:none;color:#737e90;font-size:1.2rem;cursor:pointer}.file-row button:hover{color:#fff}.add-more{justify-self:start;border:0;color:#bdc5d2;background:none;padding:5px 7px;font-size:.75rem;cursor:pointer}.add-more:hover{color:#fff}.form-error{margin:0;color:#ff9d79;font-size:.76rem}
.launch-row{margin-top:2px;padding-top:22px;border-top:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:18px}.launch-note{display:flex;gap:8px;color:#687386;font-size:.7rem}.launch-button{min-height:48px;border:0;border-radius:11px;padding:0 18px 0 20px;display:inline-flex;align-items:center;gap:18px;color:#10131a;background:var(--accent);font-weight:680;font-size:.86rem;cursor:pointer;box-shadow:0 12px 30px rgba(255,119,65,.18);transition:transform .18s,filter .18s}.launch-button svg{width:18px;fill:none;stroke:currentColor;stroke-width:2}.launch-button:hover:not(:disabled){transform:translateY(-2px);filter:brightness(1.08)}.launch-button:disabled{cursor:not-allowed;opacity:.35;box-shadow:none}
.headless-strip{max-width:1416px;margin:0 auto 70px;padding:18px 20px;display:grid;grid-template-columns:1fr auto auto;gap:24px;align-items:center;position:relative;z-index:1;border:1px solid var(--line);border-radius:14px;background:rgba(12,16,25,.78)}.headless-strip>div{display:flex;align-items:center;gap:13px}.headless-strip>div div{display:grid;gap:4px}.headless-strip b{font-size:.82rem}.headless-strip small{color:#737e90;font-size:.72rem}.terminal-dot{width:9px;height:9px;border-radius:50%;background:#7698e5;box-shadow:0 0 14px rgba(118,152,229,.7)}.headless-strip code{max-width:620px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;padding:10px 12px;color:#aeb9ce;background:#060910;border-radius:8px;font-size:.72rem}.headless-strip button{border:1px solid var(--line);border-radius:8px;padding:9px 12px;color:#b8c1d0;background:rgba(255,255,255,.035);font-size:.72rem;cursor:pointer}.headless-strip button:hover{color:#fff;border-color:rgba(255,255,255,.22)}.history-wrap{max-width:1416px;margin:0 auto;padding:0 0 70px;position:relative;z-index:1}
@media(max-width:1080px){.workspace{grid-template-columns:1fr;gap:42px;padding-top:46px}.intro{display:grid;grid-template-columns:1.1fr .9fr;column-gap:34px}.eyebrow,h1,.intro-copy{grid-column:1}.runtime-card{grid-column:2;grid-row:1/4;align-self:center}.mini-flow{grid-column:1/-1;grid-template-columns:repeat(3,1fr)}.headless-strip{margin-inline:42px;grid-template-columns:1fr auto}.headless-strip code{grid-column:1/-1;grid-row:2}.history-wrap{padding-inline:42px}}
@media(max-width:720px){.topbar{height:66px;padding:0 18px}.topbar-actions{gap:8px}.text-link{display:none}.github-link{display:none}.workspace{padding:36px 18px 38px;display:flex;flex-direction:column}.intro{display:contents}.eyebrow,h1,.intro-copy{order:1}.event-panel{order:2;border-radius:16px}.runtime-card{order:3;margin-top:8px}.mini-flow{order:4;grid-template-columns:1fr}.intro h1{font-size:clamp(3rem,14vw,4.5rem)}.panel-header{padding:20px}.privacy-badge{display:none}form{padding:22px 20px}.launch-row{align-items:stretch;flex-direction:column}.launch-button{justify-content:space-between}.headless-strip{margin:0 18px 48px;grid-template-columns:1fr}.headless-strip code{grid-column:1;grid-row:auto}.headless-strip button{justify-self:start}.history-wrap{padding:0 18px 48px}.runtime-grid{grid-template-columns:1.3fr 1fr}.runtime-grid div:last-child{display:none}}
</style>
