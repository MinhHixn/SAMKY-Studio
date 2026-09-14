<template><div class="prose" v-html="html" /></template>
<script setup>
import { computed } from 'vue'
const props = defineProps({text:{type:String,default:''}})
const escape = text => String(text).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')
const inline = text => escape(text).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
const html = computed(() => {
  let code = false, list = '', result = []
  for (const line of props.text.split('\n')) {
    if (line.startsWith('```')) { if(list){result.push(`</${list}>`);list=''};result.push(code ? '</code></pre>' : '<pre><code>');code=!code;continue }
    if(code){result.push(escape(line)+'\n');continue}
    const heading = line.match(/^(#{1,6})\s+(.*)/), item = line.match(/^\s*([-*]|\d+\.)\s+(.*)/)
    if(!item&&list){result.push(`</${list}>`);list=''}
    if(heading){const level=Math.min(heading[1].length+1,6);result.push(`<h${level}>${inline(heading[2])}</h${level}>`)}
    else if(item){const kind=/\d/.test(item[1])?'ol':'ul';if(list!==kind){if(list)result.push(`</${list}>`);result.push(`<${kind}>`);list=kind};result.push(`<li>${inline(item[2])}</li>`)}
    else if(line.startsWith('> '))result.push(`<blockquote>${inline(line.slice(2))}</blockquote>`)
    else if(/^---+$/.test(line))result.push('<hr>')
    else if(line.trim())result.push(`<p>${inline(line)}</p>`)
  }
  if(list)result.push(`</${list}>`);if(code)result.push('</code></pre>')
  return result.join('')
})
</script>
<style scoped>
.prose{line-height:1.9;font-size:16px;overflow-wrap:anywhere;color:var(--ink)}.prose :deep(p){margin:0 0 12px}.prose :deep(h2),.prose :deep(h3),.prose :deep(h4){color:var(--ink);line-height:1.35;font-weight:550;letter-spacing:-.4px;margin:27px 0 14px}.prose :deep(h2){font-size:23px}.prose :deep(h3){font-size:19px}.prose :deep(h4){font-size:18px}.prose :deep(ul),.prose :deep(ol){padding-left:22px;margin:8px 0 18px}.prose :deep(li){padding-left:4px;margin:5px 0}.prose :deep(pre){background:var(--paper);border:1px solid var(--line);padding:16px;overflow:auto;border-radius:6px;font-size:14px;line-height:1.7}.prose :deep(code){font-size:.9em;background:var(--paper);padding:2px 4px;border-radius:3px}.prose :deep(blockquote){margin:15px 0;padding:9px 18px;border-left:2px solid var(--accent);background:var(--soft)}.prose :deep(hr){border:0;border-top:1px solid var(--line);margin:24px 0}
</style>
