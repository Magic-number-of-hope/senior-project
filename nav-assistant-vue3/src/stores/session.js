import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useSessionStore = defineStore('session', () => {
  // State
  const ws = ref(null)
  const sessionId = ref('session1')
  const sessionCreated = ref(false)
  const modelProvider = ref('dashscope')
  const instructions = ref('你是车载导航助手小导。优先完成导航相关需求，回复简洁清晰，必要时追问缺失信息。')
  const agentName = ref('小导')
  const modelAvailability = ref({ dashscope: false, gemini: false, openai: false })
  const pendingUserInputTs = ref(0)
  const waitingAgentResponse = ref(false)
  const emaResponseLatencyMs = ref(0)

  // Computed
  const isConnected = computed(() => ws.value && ws.value.readyState === WebSocket.OPEN)
  const hasAvailableModel = computed(() =>
    Object.values(modelAvailability.value).some(Boolean)
  )
  const supportsTools = computed(() =>
    ['gemini', 'openai'].includes(modelProvider.value)
  )

  // Location state
  const latestLocationPayload = ref(null)
  const lastLocationSentAt = ref(0)

  // Actions
  function setWs(socket) { ws.value = socket }
  function setSessionCreated(v) { sessionCreated.value = v }

  function sendMessage(data) {
    if (ws.value && ws.value.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify(data))
    }
  }

  function sendLocationUpdate(payload, force = false) {
    if (!payload) return
    latestLocationPayload.value = payload
    if (!isConnected.value) return
    const now = Date.now()
    if (!force && now - lastLocationSentAt.value < 30000) return
    sendMessage({
      type: 'client_location_update',
      location: payload.location,
      name: payload.name || '当前位置',
      source: payload.source || 'browser',
      accuracy: payload.accuracy || null,
      timestamp: payload.timestamp || Date.now(),
    })
    lastLocationSentAt.value = now
  }

  function onUserInputCommitted() {
    pendingUserInputTs.value = Date.now()
    waitingAgentResponse.value = true
  }

  function onAgentResponseStarted() {
    if (!waitingAgentResponse.value || !pendingUserInputTs.value) return
    const latency = Date.now() - pendingUserInputTs.value
    emaResponseLatencyMs.value = emaResponseLatencyMs.value
      ? 0.75 * emaResponseLatencyMs.value + 0.25 * latency
      : latency
    waitingAgentResponse.value = false
    pendingUserInputTs.value = 0
  }

  return {
    ws, sessionId, sessionCreated, modelProvider, instructions, agentName,
    modelAvailability, pendingUserInputTs, waitingAgentResponse, emaResponseLatencyMs,
    latestLocationPayload, lastLocationSentAt,
    isConnected, hasAvailableModel, supportsTools,
    setWs, setSessionCreated, sendMessage, sendLocationUpdate,
    onUserInputCommitted, onAgentResponseStarted,
  }
})
