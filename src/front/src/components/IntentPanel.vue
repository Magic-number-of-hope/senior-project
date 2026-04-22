<template>
  <div v-show="visible">
    <!-- ── 1. 意图分析结果 ── -->
    <div v-if="intentResult" class="nav-panel">
      <div class="nav-panel-header">🧭 导航意图分析结果</div>
      <div class="nav-panel-body">
        <p>
          <span :class="['intent-badge', intentBadgeCls]">{{ intentLabel }}</span>
          置信度: {{ Math.round((intentResult.confidence || 0) * 100) }}%
          <span class="confidence-bar"
            :style="{ width: Math.round((intentResult.confidence || 0) * 80) + 'px' }"></span>
        </p>
        <table class="intent-table">
          <thead><tr><th>槽位</th><th>值</th></tr></thead>
          <tbody>
            <tr v-for="(row, i) in intentSlotRows" :key="i">
              <td>{{ row.label }}</td><td>{{ row.value }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="intentResult.needs_clarification"
          style="color:hsl(25,95%,45%);font-size:0.8rem;">
          ⚠️ 信息不完整，需要追问确认
        </p>
      </div>
    </div>

    <!-- ── 2. 路线规划结果 ── -->
    <div v-if="routeResult" class="nav-panel route-result-panel">
      <div class="nav-panel-header">🗺️ 路线规划结果</div>
      <div class="nav-panel-body">
        <p v-if="routeResult.origin_name && routeResult.destination_name">
          <strong>{{ routeResult.origin_name }}</strong> → <strong>{{ routeResult.destination_name }}</strong>
        </p>
        <p v-if="routeWaypointsText">途经点: {{ routeWaypointsText }}</p>
        <p v-if="routeDistanceText">
          距离: {{ routeDistanceText }}
          <template v-if="routeDurationText"> | 预计: {{ routeDurationText }}</template>
        </p>
        <p v-if="routeTaxiCost">预计打车费: ¥{{ routeTaxiCost }}</p>
        <p v-if="routeOptsCount > 1">可选路线: {{ routeOptsCount }} 条（可在地图下方切换）</p>
        <details v-if="routeSteps.length > 0">
          <summary>详细路线 ({{ routeSteps.length }} 步)</summary>
          <ol style="font-size:0.78rem;padding-left:1.2rem;">
            <li v-for="(s, i) in routeSteps" :key="i">{{ s.instruction || s }}</li>
          </ol>
        </details>
      </div>
    </div>

    <!-- ── 3. 缺失槽位填写 ── -->
    <div v-if="missingSlots" class="nav-panel missing-slots-panel">
      <div class="nav-panel-header">📝 请补充导航信息</div>
      <div class="nav-panel-body" style="padding:12px;">
        <template v-if="!slotFillSubmitted">
          <div v-for="slot in missingSlots" :key="slot"
            class="slot-fill-group" style="margin-bottom:12px;">
            <label style="font-weight:bold;display:block;margin-bottom:4px;">
              {{ SLOT_LABELS_FILL[slot] || slot }}
            </label>
            <!-- 出行方式：按钮选择 -->
            <div v-if="slot === 'travel_mode'"
              class="mode-buttons" style="display:flex;gap:8px;flex-wrap:wrap;">
              <button v-for="opt in modeOptions" :key="opt.value"
                class="mode-btn"
                :style="slotForm.travel_mode === opt.value
                  ? { background: '#4CAF50', color: '#fff', borderColor: '#4CAF50' } : {}"
                @click="slotForm.travel_mode = opt.value">
                {{ opt.label }}
              </button>
            </div>
            <!-- 其他槽位：文本输入 -->
            <input v-else type="text" v-model="slotForm[slot]"
              :placeholder="slot === 'poi_type'
                ? '如：加油站 / 停车场 / 咖啡店'
                : '请输入' + (SLOT_LABELS_FILL[slot] || slot)"
              style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;font-size:14px;" />
          </div>
          <button @click="submitSlotFill"
            style="width:100%;padding:10px;background:#1976D2;color:#fff;border:none;border-radius:6px;font-size:15px;cursor:pointer;margin-top:8px;">
            确认提交
          </button>
        </template>
        <div v-else style="padding:12px;color:#2e7d32;font-weight:bold;">
          ✅ 已提交，正在分析导航...
        </div>
      </div>
    </div>

    <!-- ── 4. POI 候选列表 ── -->
    <div v-if="poiGroupData" class="nav-panel">
      <div class="nav-panel-header">📍 找到多个地点，请选择</div>
      <div class="nav-panel-body">
        <div style="display:flex;justify-content:flex-end;margin-bottom:8px;">
          <button @click="selectAllPois"
            style="padding:6px 10px;background:#0ea5e9;color:#fff;border:none;border-radius:6px;font-size:13px;cursor:pointer;">
            一键全部选择（每组第一个）
          </button>
        </div>
        <div v-for="gName in poiGroupNames" :key="gName" class="poi-group">
          <template v-if="!poiGroupSelected[gName]">
            <div style="font-weight:bold;margin:6px 0 2px;">
              📌 {{ POI_GROUP_LABELS[gName] || gName }}
            </div>
            <ul class="poi-candidates">
              <li v-for="entry in poiGroupData[gName]" :key="entry.idx"
                @click="selectPoi(entry, gName)">
                <strong>{{ entry.poi.name || '地点' }}</strong>
                <br><span style="color:#666;">{{ entry.poi.address || '' }}</span>
              </li>
            </ul>
          </template>
          <div v-else style="padding:6px;color:#2e7d32;font-weight:bold;">
            ✅ 已选择: {{ poiGroupSelected[gName] }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
/* global defineEmits, defineExpose */
import { ref, reactive, computed } from 'vue'

/* ═══ 常量 ═══ */
const INTENT_LABELS = {
  basic_navigation: '基础导航',
  life_service: '生活服务',
  multi_destination: '多目的地',
  compound_constraint: '复合约束'
}
const INTENT_CSS = {
  basic_navigation: 'basic',
  life_service: 'life',
  multi_destination: 'multi',
  compound_constraint: 'compound'
}
const SLOT_LABELS_TABLE = {
  origin: '出发地',
  destination: '目的地',
  waypoints: '途经点',
  travel_mode: '出行方式',
  time_constraint: '时间约束',
  preference: '偏好',
  poi_type: 'POI类型',
  poi_constraint: 'POI约束',
  sequence: '顺序'
}
const SLOT_LABELS_FILL = {
  origin: '出发地',
  destination: '目的地',
  travel_mode: '出行方式',
  poi_type: '目标地点类型'
}
const MODE_LABELS_MAP = {
  driving: '驾车', walking: '步行', transit: '公交', bicycling: '骑行'
}
const POI_GROUP_LABELS = {
  origin: '起点候选',
  destination: '终点候选',
  waypoint: '途经点候选',
  other: '候选地点'
}

const modeOptions = [
  { value: 'driving', label: '🚗 驾车' },
  { value: 'walking', label: '🚶 步行' },
  { value: 'transit', label: '🚌 公交' },
  { value: 'bicycling', label: '🚲 骑行' }
]

const emit = defineEmits(['message', 'slot-fill', 'poi-select'])

/* ═══ 面板可见性 ═══ */
const visible = ref(false)

/* ─── 1. 意图分析 ─── */
const intentResult = ref(null)

const intentBadgeCls = computed(() =>
  INTENT_CSS[intentResult.value?.intent_type] || 'basic')

const intentLabel = computed(() =>
  INTENT_LABELS[intentResult.value?.intent_type] || intentResult.value?.intent_type || 'unknown')

const intentSlotRows = computed(() => {
  const slots = intentResult.value?.slots
  if (!slots) return []
  return Object.entries(slots)
    .filter(([, v]) => v != null && v !== '' && !(Array.isArray(v) && v.length === 0))
    .map(([k, v]) => ({
      label: SLOT_LABELS_TABLE[k] || k,
      value: Array.isArray(v) ? v.join(' → ') : (MODE_LABELS_MAP[v] || String(v))
    }))
})

function renderIntentPanel (result) {
  intentResult.value = result
  visible.value = true
  const label = INTENT_LABELS[result.intent_type] || result.intent_type
  const conf = Math.round((result.confidence || 0) * 100)
  emit('message', { sender: 'System', text: '🧭 意图识别: ' + label + ' (置信度 ' + conf + '%)' })
}

/* ─── 2. 路线结果 ─── */
const routeResult = ref(null)
const routeOptionsArr = ref([])
const routeSelIdx = ref(0)
let lastRouteRenderKey = ''

const activeRouteOption = computed(() =>
  routeOptionsArr.value[routeSelIdx.value] || routeOptionsArr.value[0] || {})

const routeSteps = computed(() => {
  const opt = activeRouteOption.value
  if (Array.isArray(opt.steps) && opt.steps.length > 0) return opt.steps
  return Array.isArray(routeResult.value?.steps) ? routeResult.value.steps : []
})
const routeDistance = computed(() =>
  activeRouteOption.value.distance || routeResult.value?.distance || '')
const routeDuration = computed(() =>
  activeRouteOption.value.duration || routeResult.value?.duration || '')
const routeTaxiCost = computed(() =>
  activeRouteOption.value.taxi_cost || routeResult.value?.taxi_cost || '')
const routeOptsCount = computed(() => routeOptionsArr.value.length)
const routeWaypointsText = computed(() => {
  const wp = routeResult.value?.waypoints
  return Array.isArray(wp) && wp.length > 0 ? wp.join(' → ') : ''
})
const routeDistanceText = computed(() => {
  const d = routeDistance.value
  return d ? (parseFloat(d) / 1000).toFixed(1) + ' 公里' : ''
})
const routeDurationText = computed(() => {
  const d = routeDuration.value
  return d ? Math.round(parseFloat(d) / 60) + ' 分钟' : ''
})

function renderRouteResult (route, routeOptions, selectedIdx) {
  if (!route) return

  const opts = routeOptions || []
  const idx = (selectedIdx != null && selectedIdx >= 0 && selectedIdx < opts.length)
    ? selectedIdx
    : 0
  const activeOpt = opts[idx] || opts[0] || {}

  const displaySteps = (Array.isArray(activeOpt.steps) && activeOpt.steps.length > 0)
    ? activeOpt.steps
    : (Array.isArray(route.steps) ? route.steps : [])
  const displayDistance = activeOpt.distance || route.distance || ''
  const displayDuration = activeOpt.duration || route.duration || ''
  const displayTaxiCost = activeOpt.taxi_cost || route.taxi_cost || ''

  // 去重 key —— 同一路线不重复渲染
  const routeKey = [
    route.origin_name || '', route.destination_name || '',
    displayDistance, displayDuration, displayTaxiCost,
    Array.isArray(displaySteps) ? displaySteps.length : 0,
    opts.length, idx,
    route.polyline ? route.polyline.length : 0
  ].join('|')
  if (routeKey && routeKey === lastRouteRenderKey) return
  lastRouteRenderKey = routeKey

  routeOptionsArr.value = opts
  routeSelIdx.value = idx
  routeResult.value = route
  visible.value = true

  // 摘要消息
  const km = displayDistance ? (parseFloat(displayDistance) / 1000).toFixed(1) + 'km' : ''
  const min = displayDuration ? Math.round(parseFloat(displayDuration) / 60) + 'min' : ''
  emit('message', {
    sender: 'System',
    text: '🗺️ 路线: ' + (route.origin_name || '') + ' → ' + (route.destination_name || '') + ' ' + km + ' ' + min
  })
}

/* ─── 3. 缺失槽位 ─── */
const missingSlots = ref(null)
const slotFillSubmitted = ref(false)
const slotForm = reactive({})

function renderMissingSlots (missing, currentSlots) {
  if (!missing || missing.length === 0) return
  // 重置表单
  Object.keys(slotForm).forEach(k => delete slotForm[k])
  if (currentSlots) {
    for (const [k, v] of Object.entries(currentSlots)) {
      slotForm[k] = v
    }
  }
  missingSlots.value = missing
  slotFillSubmitted.value = false
  visible.value = true
}

function submitSlotFill () {
  const filled = {}
  if (missingSlots.value) {
    missingSlots.value.forEach(slot => {
      if (slot !== 'travel_mode' && slotForm[slot] && String(slotForm[slot]).trim()) {
        filled[slot] = String(slotForm[slot]).trim()
      }
    })
  }
  if (slotForm.travel_mode) filled.travel_mode = slotForm.travel_mode

  emit('slot-fill', filled)

  // 显示已提交的信息
  const parts = []
  if (filled.origin) parts.push('起点: ' + filled.origin)
  if (filled.destination) parts.push('终点: ' + filled.destination)
  if (filled.travel_mode) {
    parts.push('方式: ' + (MODE_LABELS_MAP[filled.travel_mode] || filled.travel_mode))
  }
  emit('message', { sender: 'User', text: '补充信息: ' + parts.join(', ') })

  slotFillSubmitted.value = true
  setTimeout(() => { missingSlots.value = null }, 2000)
}

/* ─── 4. POI 候选 ─── */
const poiGroupData = ref(null)
const poiGroupNames = ref([])
const poiGroupSelected = reactive({})
let poiFinalCandidates = []
let poiClearTimer = null

function renderPOICandidates (candidates, originCandidates, destinationCandidates) {
  if (poiClearTimer) {
    clearTimeout(poiClearTimer)
    poiClearTimer = null
  }

  const finalCandidates = Array.isArray(candidates) ? candidates.slice() : []

  // 后端若只给分组候选，这里做前端兜底扁平化
  if (finalCandidates.length === 0) {
    const origin = Array.isArray(originCandidates) ? originCandidates : []
    const dest = Array.isArray(destinationCandidates) ? destinationCandidates : []
    origin.forEach(item => finalCandidates.push({ ...item, selection_group: 'origin' }))
    dest.forEach(item => finalCandidates.push({ ...item, selection_group: 'destination' }))
  }

  if (!finalCandidates.length) {
    emit('message', { sender: 'System', text: '⚠️ 找到了歧义地点，但候选列表为空' })
    return
  }

  poiFinalCandidates = finalCandidates

  // 按 selection_group 分组
  const groups = {}
  finalCandidates.forEach((poi, i) => {
    const g = poi.selection_group || 'other'
    if (!groups[g]) groups[g] = []
    groups[g].push({ poi, idx: i })
  })

  // 重置选择状态
  Object.keys(poiGroupSelected).forEach(k => delete poiGroupSelected[k])
  poiGroupData.value = groups
  poiGroupNames.value = Object.keys(groups)
  visible.value = true
}

function selectPoi (entry, groupName) {
  if (!entry) return
  const selected = poiFinalCandidates[entry.idx]

  emit('message', { sender: 'User', text: '选择: ' + selected.name })
  emit('poi-select', { index: entry.idx, poi: selected })

  // 标记该分组已选
  poiGroupSelected[groupName] = selected.name

  // 所有分组选完后自动关闭
  const allDone = poiGroupNames.value.every(g => !!poiGroupSelected[g])
  if (allDone) {
    if (poiClearTimer) clearTimeout(poiClearTimer)
    poiClearTimer = setTimeout(() => {
      poiGroupData.value = null
      poiClearTimer = null
    }, 600)
  }
}

function selectAllPois () {
  poiGroupNames.value.forEach(gName => {
    const items = poiGroupData.value?.[gName] || []
    if (items.length > 0 && !poiGroupSelected[gName]) {
      selectPoi(items[0], gName)
    }
  })
}

/* ═══ 暴露方法给父组件 ═══ */
defineExpose({
  renderIntentPanel,
  renderRouteResult,
  renderMissingSlots,
  renderPOICandidates
})
</script>
