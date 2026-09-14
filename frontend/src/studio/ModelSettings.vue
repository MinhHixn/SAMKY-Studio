<template>
  <div class="model-settings">
    <div class="setting-heading"><span class="field-label">{{ t('model') }}</span><span class="model-symbol">⌘</span></div>
    <div class="mode-switch" role="group" :aria-label="t('model')"><button v-for="mode in ['offline','online']" :key="mode" type="button" :aria-pressed="settings.mode === mode" :class="{active:settings.mode === mode}" @click="setMode(mode)"><span>{{ mode === 'offline' ? '◉' : '◎' }}</span>{{ t(mode) }}</button></div>
    <p class="field-hint">{{ t(settings.mode === 'offline' ? 'offlineHint' : 'onlineHint') }}</p>
    <label class="field"><span>{{ t('endpoint') }}</span><input v-model="settings.base_url" type="url" required spellcheck="false" placeholder="http://localhost:11434/v1" /></label>
    <label class="field"><span>{{ t('modelId') }}</span><input v-model="settings.model" list="studio-models" required maxlength="200" placeholder="model-name" spellcheck="false" /><datalist id="studio-models"><option v-for="model in models" :key="model" :value="model" /></datalist></label>
    <div class="field"><label class="field-label" for="api-key">{{ t('key') }} <small class="muted">· {{ t('optional') }}</small></label><div class="key-input"><input id="api-key" :value="apiKey" @input="editKey($event.target.value)" :type="showKey ? 'text' : 'password'" autocomplete="off" spellcheck="false" :placeholder="savedKey ? '••••••••••••••••' : t('keyOptional')" /><button type="button" class="text-button" @click="showKey = !showKey">{{ t(showKey ? 'hide' : 'show') }}</button></div><div class="key-help"><small>{{ t(savedKey ? 'keySaved' : 'keyHint') }}</small><button v-if="savedKey || apiKey" class="text-button" type="button" @click="editKey('')">{{ t('clearKey') }}</button></div></div>
    <div class="model-actions"><button type="button" class="text-button discover" :disabled="checking || !settings.base_url" @click="discover">↻ {{ t(checking ? 'checking' : 'discover') }}</button><span v-if="verified" class="success-message">{{ t('modelReady') }}</span></div>
    <p v-if="error" role="alert" class="error-message">{{ error }}</p>
  </div>
</template>
<script setup>
import { reactive, ref, onMounted, watch } from 'vue'
import service from '../api'
import { useStudioText } from './i18n'
const { t } = useStudioText()
const settings = reactive({mode:'offline',base_url:'http://localhost:11434/v1',model:'qwen2.5:7b'})
const apiKey = ref(''), savedKey = ref(false), showKey = ref(false), checking = ref(false), verified = ref(false), error = ref(''), models = ref([])
let original = null, keyEdited = false, edited = false
watch(settings, () => { edited = true; verified.value = false; error.value = '' }, {flush:'sync'})
watch(() => [settings.base_url, settings.mode], () => { if (original) { savedKey.value = false; apiKey.value = ''; keyEdited = true } }, {flush:'sync'})
function editKey(value) { apiKey.value = value; keyEdited = true; savedKey.value = false; verified.value = false }
function setMode(mode) { if (mode === settings.mode) return; settings.mode = mode; settings.base_url = mode === 'offline' ? 'http://localhost:11434/v1' : 'https://openrouter.ai/api/v1'; settings.model = mode === 'offline' ? 'qwen2.5:7b' : ''; editKey(''); models.value = [] }
function payload() { return {...settings, ...(keyEdited ? {api_key:apiKey.value} : {})} }
async function discover() { checking.value = true; error.value = ''; const current = JSON.stringify(payload()); try { const res = await service.post('/api/runtime/models',payload()); if (current !== JSON.stringify(payload())) return; models.value = res.data.models; verified.value = true } catch (e) { error.value = e.response?.data?.error || e.message } finally { checking.value = false } }
async function apply() {
  if (original && !keyEdited && settings.mode === original.mode && settings.base_url === original.base_url && settings.model === original.model) return
  const res = await service.post('/api/runtime',payload())
  original = {...res.data}; savedKey.value = res.data.has_api_key; apiKey.value = ''; keyEdited = false
}
onMounted(async () => { try { const res = await service.get('/api/runtime'); if (!edited) { Object.assign(settings,{mode:res.data.mode,base_url:res.data.base_url,model:res.data.model}); original = {...res.data}; savedKey.value = res.data.has_api_key; keyEdited = false } } catch { /* Form stays usable while the server starts. */ } })
defineExpose({apply})
</script>
<style scoped>
.model-settings{display:grid;gap:17px}.setting-heading{display:flex;justify-content:space-between;align-items:center}.model-symbol{font-size:18px;color:var(--muted)}.mode-switch{display:flex;border:1px solid var(--line);padding:4px;border-radius:7px;background:var(--soft);gap:4px}.mode-switch button{display:flex;gap:9px;align-items:center;justify-content:center;flex:1;border:0;background:transparent;font-size:14px;padding:9px;border-radius:4px;color:var(--muted)}.mode-switch button.active{background:var(--surface);box-shadow:0 1px 3px #20302012;color:var(--accent)}.key-input{position:relative}.key-input input{padding-right:55px}.key-input button{position:absolute;right:12px;top:5px;font-size:12px}.key-help{display:flex;gap:10px;align-items:start}.key-help small{flex:1;font-size:12px}.key-help button{font-size:12px;white-space:nowrap;padding:0}.model-actions{display:flex;align-items:center;justify-content:space-between;gap:8px}.discover{color:var(--accent);font-size:14px;padding:0}
</style>
