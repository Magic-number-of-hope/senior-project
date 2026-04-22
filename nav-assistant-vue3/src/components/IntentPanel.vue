<template>
  <div v-if="nav.intentResult" class="nav-panel card">
    <div class="nav-panel-header">🧭 导航意图分析结果</div>
    <div class="nav-panel-body">
      <p>
        <span class="intent-badge" :class="badgeCls">{{ intentLabel }}</span>
        置信度: {{ Math.round((nav.intentResult.confidence || 0) * 100) }}%
        <span
          class="confidence-bar"
          :style="{ width: Math.round((nav.intentResult.confidence || 0) * 80) + 'px' }"
        ></span>
      </p>

      <table class="intent-table" v-if="slotEntries.length">
        <thead><tr><th>槽位</th><th>值</th></tr></thead>
        <tbody>
          <tr v-for="[key, val] in slotEntries" :key="key">
            <td>{{ SLOT_LABELS[key] || key }}</td>
            <td>{{ formatSlotValue(key, val) }}</td>
          </tr>
        </tbody>
      </table>

      <p v-if="nav.intentResult.needs_clarification" class="clarify-warn">
        ⚠️ 信息不完整，需要追问确认
      </p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useNavStore } from '../stores/nav'
import { INTENT_LABELS, INTENT_CSS, SLOT_LABELS, MODE_LABELS } from '../utils/constants'

const nav = useNavStore()

const intentType = computed(() => nav.intentResult?.intent_type || 'unknown')
const badgeCls = computed(() => INTENT_CSS[intentType.value] || 'basic')
const intentLabel = computed(() => INTENT_LABELS[intentType.value] || intentType.value)

const slotEntries = computed(() => {
  const slots = nav.intentResult?.slots || {}
  return Object.entries(slots).filter(([, v]) => {
    if (v == null || v === '') return false
    if (Array.isArray(v) && v.length === 0) return false
    return true
  })
})

function formatSlotValue(key, val) {
  if (Array.isArray(val)) return val.join(' → ')
  if (key === 'travel_mode') return MODE_LABELS[val] || String(val)
  return String(val)
}
</script>

<style scoped>
.nav-panel-header {
  background: var(--blue);
  color: white;
  padding: 0.625rem 1rem;
  font-weight: 600;
  font-size: 0.875rem;
}
.nav-panel-body { padding: 1rem; }
.intent-badge {
  display: inline-block;
  padding: 0.125rem 0.5rem;
  border-radius: 0.25rem;
  font-size: 0.75rem;
  font-weight: 500;
  margin-right: 0.5rem;
}
.intent-badge.basic { background: hsl(200, 95%, 90%); color: hsl(200, 95%, 30%); }
.intent-badge.life { background: hsl(142, 71%, 90%); color: hsl(142, 71%, 30%); }
.intent-badge.multi { background: hsl(280, 85%, 90%); color: hsl(280, 85%, 30%); }
.intent-badge.compound { background: hsl(25, 95%, 90%); color: hsl(25, 95%, 30%); }
.confidence-bar {
  display: inline-block;
  height: 6px;
  border-radius: 3px;
  background: var(--green);
  margin-left: 0.5rem;
  vertical-align: middle;
}
.intent-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
  margin: 0.75rem 0;
}
.intent-table th,
.intent-table td {
  border: 1px solid var(--border);
  padding: 0.5rem 0.75rem;
  text-align: left;
}
.intent-table th {
  background: var(--bg-muted);
  font-weight: 600;
  color: var(--text-secondary);
}
.clarify-warn {
  color: hsl(25, 95%, 45%);
  font-size: 0.8rem;
}
</style>
