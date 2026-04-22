<template>
  <div v-if="nav.routeResult" class="nav-panel card">
    <div class="nav-panel-header">🗺️ 路线规划结果</div>
    <div class="nav-panel-body">
      <p v-if="route.origin_name && route.destination_name">
        <strong>{{ route.origin_name }}</strong> → <strong>{{ route.destination_name }}</strong>
      </p>
      <p v-if="route.waypoints?.length">途经点: {{ route.waypoints.join(' → ') }}</p>
      <p v-if="displayDistance">
        距离: {{ km }} 公里
        <template v-if="displayDuration"> | 预计: {{ minutes }} 分钟</template>
      </p>
      <p v-if="displayTaxiCost">预计打车费: ¥{{ displayTaxiCost }}</p>
      <p v-if="routeOptions.length > 1">可选路线: {{ routeOptions.length }} 条</p>

      <details v-if="displaySteps.length > 0">
        <summary>详细路线 ({{ displaySteps.length }} 步)</summary>
        <ol class="steps-list">
          <li v-for="(step, i) in displaySteps" :key="i">
            {{ step.instruction || step }}
          </li>
        </ol>
      </details>
    </div>

    <!-- Route selector chips -->
    <div v-if="routeOptions.length > 1" class="route-selector">
      <div class="route-selector-title">选择路线方案：</div>
      <div class="route-chips">
        <button
          v-for="(opt, idx) in routeOptions"
          :key="idx"
          class="route-chip"
          :class="{ active: nav.selectedRouteIndex === idx }"
          @click="selectRoute(idx)"
        >
          {{ opt.summary || `方案${idx + 1}` }}
          <template v-if="opt.distance">
            ({{ (parseFloat(opt.distance) / 1000).toFixed(1) }}km)
          </template>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useNavStore } from '../stores/nav'
import { getRouteOptions } from '../utils/map'

const emit = defineEmits(['selectRoute'])
const nav = useNavStore()

const route = computed(() => nav.routeResult || {})
const routeOptions = computed(() => getRouteOptions(route.value))

const activeOption = computed(() => {
  const opts = routeOptions.value
  const idx = nav.selectedRouteIndex
  return opts[idx] || opts[0] || {}
})

const displaySteps = computed(() =>
  activeOption.value.steps?.length ? activeOption.value.steps : (route.value.steps || [])
)
const displayDistance = computed(() => activeOption.value.distance || route.value.distance || '')
const displayDuration = computed(() => activeOption.value.duration || route.value.duration || '')
const displayTaxiCost = computed(() => activeOption.value.taxi_cost || route.value.taxi_cost || '')

const km = computed(() => displayDistance.value ? (parseFloat(displayDistance.value) / 1000).toFixed(1) : '')
const minutes = computed(() => displayDuration.value ? Math.round(parseFloat(displayDuration.value) / 60) : '')

function selectRoute(idx) {
  nav.setSelectedRouteIndex(idx)
  emit('selectRoute', idx)
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
.nav-panel-body p { margin-bottom: 0.5rem; }
.steps-list {
  font-size: 0.78rem;
  padding-left: 1.2rem;
  margin-top: 0.5rem;
}
.steps-list li { margin-bottom: 0.25rem; }
.route-selector {
  padding: 0.5rem 1rem 0.75rem;
  border-top: 1px solid var(--border);
}
.route-selector-title {
  font-size: 0.8rem;
  color: #1f3340;
  font-weight: 600;
  margin-bottom: 0.45rem;
}
.route-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.route-chip {
  border: 1px solid #b9cad5;
  border-radius: 999px;
  background: #f6fafc;
  color: #173849;
  font-size: 0.78rem;
  padding: 0.3rem 0.7rem;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s ease;
}
.route-chip.active {
  border-color: var(--brand);
  background: #e8f8f4;
  color: #0b4b45;
  font-weight: 600;
}
</style>
