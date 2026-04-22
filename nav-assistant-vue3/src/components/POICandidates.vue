<template>
  <div v-if="groupedCandidates && Object.keys(groupedCandidates).length > 0" class="nav-panel card">
    <div class="nav-panel-header">📍 找到多个地点，请选择</div>
    <div class="nav-panel-body">
      <div class="select-all-row">
        <button class="select-all-btn" @click="selectAll">一键全部选择（每组第一个）</button>
      </div>

      <div
        v-for="(items, groupName) in groupedCandidates"
        :key="groupName"
        class="poi-group"
      >
        <div v-if="!selectedGroups[groupName]" class="poi-group-label">
          📌 {{ GROUP_LABELS[groupName] || groupName }}
        </div>

        <div v-if="selectedGroups[groupName]" class="poi-selected-mark">
          ✅ 已选择: {{ selectedGroups[groupName] }}
        </div>

        <ul v-else class="poi-list">
          <li
            v-for="entry in items"
            :key="entry.idx"
            @click="selectPoi(entry, groupName)"
          >
            <strong>{{ entry.poi.name || '地点' }}</strong>
            <br><span class="poi-address">{{ entry.poi.address || '' }}</span>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive } from 'vue'
import { useNavStore } from '../stores/nav'
import { useSessionStore } from '../stores/session'
import { useMessageStore } from '../stores/messages'

const nav = useNavStore()
const session = useSessionStore()
const messages = useMessageStore()

const GROUP_LABELS = { origin: '起点候选', destination: '终点候选', other: '候选地点' }

const selectedGroups = reactive({})

const groupedCandidates = computed(() => {
  const groups = {}
  nav.poiCandidates.forEach((poi, i) => {
    const g = poi.selection_group || 'other'
    if (!groups[g]) groups[g] = []
    groups[g].push({ poi, idx: i })
  })
  return groups
})

function selectPoi(entry, groupName) {
  const selected = nav.poiCandidates[entry.idx]
  messages.addMessage('User', '选择: ' + selected.name)
  session.sendMessage({ type: 'nav_poi_select', index: entry.idx, poi: selected })
  selectedGroups[groupName] = selected.name

  // Check if all groups selected
  const allGroupNames = Object.keys(groupedCandidates.value)
  const allDone = allGroupNames.every(g => selectedGroups[g])
  if (allDone) {
    setTimeout(() => nav.clearPOICandidates(), 600)
  }
}

function selectAll() {
  const groups = groupedCandidates.value
  Object.entries(groups).forEach(([gName, items]) => {
    if (items.length > 0 && !selectedGroups[gName]) {
      selectPoi(items[0], gName)
    }
  })
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
.select-all-row {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}
.select-all-btn {
  padding: 6px 10px;
  background: #0ea5e9;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  font-family: inherit;
}
.poi-group-label {
  font-weight: bold;
  margin: 6px 0 2px;
}
.poi-selected-mark {
  padding: 6px;
  color: #2e7d32;
  font-weight: bold;
}
.poi-list {
  list-style: none;
  padding: 0;
}
.poi-list li {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  margin-bottom: 0.375rem;
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 0.8rem;
}
.poi-list li:hover {
  background: var(--blue-light);
  border-color: var(--blue);
}
.poi-address { color: #666; }
</style>
