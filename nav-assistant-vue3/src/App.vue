<template>
  <div class="app-container">
    <!-- Header -->
    <div class="app-header">
      <h1>小导 | 车载导航助手</h1>
      <p class="hero-subtitle">支持语音和文本输入，自动完成意图识别、槽位提取、POI 检索与路线规划。</p>
    </div>

    <!-- Configuration -->
    <ConfigPanel />

    <!-- Error Banner -->
    <ErrorBanner :message="errorMsg" />

    <!-- Control Buttons -->
    <ControlBar :audio="audio" :video="video" :wsManager="wsManager" />

    <!-- Video Preview -->
    <VideoPreview :isActive="video.isRecordingVideo.value" />

    <!-- Fatigue Panel -->
    <FatiguePanel />

    <!-- Text Input -->
    <TextInput :wsManager="wsManager" />

    <!-- Nav Status -->
    <NavStatus />

    <!-- Map -->
    <MapContainer ref="mapContainerRef" />

    <!-- Navigation Analysis Panels -->
    <div class="nav-panels">
      <IntentPanel />
      <RouteResult @selectRoute="handleRouteSelect" />
      <POICandidates />
      <MissingSlots />
    </div>

    <!-- Messages -->
    <MessageList />
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useSessionStore } from './stores/session'
import { useNavStore } from './stores/nav'
import { useMessageStore } from './stores/messages'

import { useWebSocket } from './composables/useWebSocket'
import { useAudio } from './composables/useAudio'
import { useVideo } from './composables/useVideo'
import { useAMap } from './composables/useAMap'

import ConfigPanel from './components/ConfigPanel.vue'
import ErrorBanner from './components/ErrorBanner.vue'
import ControlBar from './components/ControlBar.vue'
import VideoPreview from './components/VideoPreview.vue'
import FatiguePanel from './components/FatiguePanel.vue'
import TextInput from './components/TextInput.vue'
import NavStatus from './components/NavStatus.vue'
import MapContainer from './components/MapContainer.vue'
import IntentPanel from './components/IntentPanel.vue'
import RouteResult from './components/RouteResult.vue'
import POICandidates from './components/POICandidates.vue'
import MissingSlots from './components/MissingSlots.vue'
import MessageList from './components/MessageList.vue'

const session = useSessionStore()
const nav = useNavStore()
const messages = useMessageStore()

const errorMsg = ref('')
const mapContainerRef = ref(null)

// Composables
const wsManager = useWebSocket()
const audio = useAudio()
const video = useVideo()
const amap = useAMap()

// Wire up route result handler to plan via JS API then display
wsManager.setRouteResultHandler(async (routeData) => {
  try {
    const planned = await amap.planRouteByJsApi(routeData || {})
    nav.setRouteResult(planned)
    await amap.showRouteOnMap(planned, nav.selectedRouteIndex)
    // Send planned route back to backend
    session.sendMessage({ type: 'nav_planned_route', route: planned })
    const km = planned.distance ? (parseFloat(planned.distance) / 1000).toFixed(1) + 'km' : ''
    const min = planned.duration ? Math.round(parseFloat(planned.duration) / 60) + 'min' : ''
    messages.addMessage('System', `🗺️ 路线: ${planned.origin_name || ''} → ${planned.destination_name || ''} ${km} ${min}`)
  } catch (err) {
    console.error('Route planning error:', err)
    nav.setRouteResult(routeData)
  }
})

// Wire up POI candidates to show on map
wsManager.setPOICandidatesHandler((candidates) => {
  amap.showCandidatesOnMap(candidates)
})

// Route selection handler
async function handleRouteSelect(idx) {
  if (nav.routeResult) {
    await amap.showRouteOnMap(nav.routeResult, idx)
  }
}

onMounted(async () => {
  await amap.initAMap()
  wsManager.connect()
})

onBeforeUnmount(() => {
  amap.destroyMap()
})
</script>

<style scoped>
.app-container {
  max-width: 900px;
  margin: 0 auto;
  padding: 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  min-height: 100vh;
}
.app-header h1 {
  font-size: 2.2rem;
  font-weight: 700;
  color: #0f2a35;
  letter-spacing: -0.03em;
}
.hero-subtitle {
  color: #34505f;
  font-size: 0.95rem;
  margin-top: 0.35rem;
}
.nav-panels {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
</style>
