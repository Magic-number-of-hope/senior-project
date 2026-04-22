<template>
  <div v-if="nav.missingSlots.length > 0 && !submitted" class="nav-panel card">
    <div class="nav-panel-header">📝 请补充导航信息</div>
    <div class="nav-panel-body">
      <div v-for="slot in nav.missingSlots" :key="slot" class="slot-group">
        <label class="slot-label">{{ SLOT_LABELS[slot] || slot }}</label>

        <div v-if="slot === 'travel_mode'" class="mode-buttons">
          <button
            v-for="opt in MODE_OPTIONS"
            :key="opt.value"
            class="mode-btn"
            :class="{ selected: filledSlots.travel_mode === opt.value }"
            @click="filledSlots.travel_mode = opt.value"
          >
            {{ opt.label }}
          </button>
        </div>

        <input
          v-else
          type="text"
          v-model="filledSlots[slot]"
          :placeholder="getPlaceholder(slot)"
        />
      </div>

      <button class="submit-btn" @click="submitSlots">确认提交</button>
    </div>
  </div>

  <div v-if="submitted" class="submitted-mark card">
    <div style="padding:12px;color:#2e7d32;font-weight:bold;">✅ 已提交，正在分析导航...</div>
  </div>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { useNavStore } from '../stores/nav'
import { useSessionStore } from '../stores/session'
import { useMessageStore } from '../stores/messages'
import { SLOT_LABELS, MODE_OPTIONS, MODE_LABELS } from '../utils/constants'

const nav = useNavStore()
const session = useSessionStore()
const messages = useMessageStore()

const filledSlots = reactive({})
const submitted = ref(false)

// Reset when new missing slots arrive
watch(() => nav.missingSlots, (newSlots) => {
  submitted.value = false
  Object.keys(filledSlots).forEach(k => delete filledSlots[k])
  // Pre-fill current slots
  if (nav.currentSlots) {
    Object.entries(nav.currentSlots).forEach(([k, v]) => {
      if (v) filledSlots[k] = v
    })
  }
}, { deep: true })

function getPlaceholder(slot) {
  if (slot === 'poi_type') return '如：加油站 / 停车场 / 咖啡店'
  return '请输入' + (SLOT_LABELS[slot] || slot)
}

function submitSlots() {
  const filled = {}
  Object.entries(filledSlots).forEach(([k, v]) => {
    if (typeof v === 'string' ? v.trim() : v) filled[k] = typeof v === 'string' ? v.trim() : v
  })

  session.sendMessage({ type: 'nav_slot_fill', slots: filled })

  const parts = []
  if (filled.origin) parts.push('起点: ' + filled.origin)
  if (filled.destination) parts.push('终点: ' + filled.destination)
  if (filled.travel_mode) parts.push('方式: ' + (MODE_LABELS[filled.travel_mode] || filled.travel_mode))
  messages.addMessage('User', '补充信息: ' + parts.join(', '))

  submitted.value = true
  setTimeout(() => {
    nav.clearMissingSlots()
    submitted.value = false
  }, 2000)
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
.nav-panel-body { padding: 12px; }
.slot-group { margin-bottom: 12px; }
.slot-label {
  font-weight: bold;
  display: block;
  margin-bottom: 4px;
  font-size: 0.875rem;
}
.mode-buttons { display: flex; gap: 8px; flex-wrap: wrap; }
.mode-btn {
  padding: 8px 16px;
  border: 2px solid #ccc;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.15s ease;
  font-family: inherit;
}
.mode-btn:hover { border-color: #4CAF50; background: #f1f8e9; }
.mode-btn.selected { background: #4CAF50; color: #fff; border-color: #4CAF50; }
.submit-btn {
  width: 100%;
  padding: 10px;
  background: #1976D2;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 15px;
  cursor: pointer;
  margin-top: 8px;
  font-family: inherit;
}
.submitted-mark { margin: 0.5rem 0; }
</style>
