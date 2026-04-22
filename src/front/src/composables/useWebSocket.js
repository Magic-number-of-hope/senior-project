import { ref } from 'vue'

export function useWebSocket () {
  const ws = ref(null)
  const sessionId = 'session1'
  const sessionCreated = ref(false)
  const latestLocationPayload = ref(null)
  let lastLocationSentAt = 0

  // 供外部注入的回调
  let onMessageCallback = null
  let onOpenCallback = null
  let onCloseCallback = null

  function setOnMessage (cb) { onMessageCallback = cb }
  function setOnOpen (cb) { onOpenCallback = cb }
  function setOnClose (cb) { onCloseCallback = cb }

  function isConnected () {
    return ws.value && ws.value.readyState === WebSocket.OPEN
  }

  function connect () {
    const userId = 'You'
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/${userId}/${sessionId}`

    console.log(`Connecting to WebSocket: ${wsUrl}`)
    ws.value = new WebSocket(wsUrl)

    ws.value.onopen = function () {
      if (onOpenCallback) onOpenCallback()
    }

    ws.value.onmessage = async function (event) {
      try {
        const data = JSON.parse(event.data)
        console.log('Received message:', data)
        if (onMessageCallback) await onMessageCallback(data)
      } catch (e) {
        console.error('Error processing message:', e)
      }
    }

    ws.value.onclose = function () {
      sessionCreated.value = false
      if (onCloseCallback) onCloseCallback()
    }

    ws.value.onerror = function () {
      if (onCloseCallback) onCloseCallback()
    }
  }

  function disconnect () {
    if (ws.value) {
      ws.value.close()
    }
    sessionCreated.value = false
  }

  function send (obj) {
    if (isConnected()) {
      ws.value.send(JSON.stringify(obj))
    }
  }

  async function ensureSessionCreated (instructions, agentName, modelProvider) {
    if (sessionCreated.value) return

    if (!instructions) throw new Error('系统指令不能为空')
    if (!isConnected()) throw new Error('WebSocket 尚未连接')

    send({
      type: 'client_session_create',
      config: {
        instructions,
        agent_name: agentName || '小导',
        model_provider: modelProvider || 'dashscope'
      }
    })

    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error('会话创建超时'))
      }, 5000)
      const checkSession = setInterval(() => {
        if (sessionCreated.value) {
          clearTimeout(timeout)
          clearInterval(checkSession)
          resolve()
        }
      }, 100)
    })
  }

  function sendLocationUpdate (payload, force) {
    if (!payload) return
    latestLocationPayload.value = payload
    if (!isConnected()) return

    const now = Date.now()
    if (!force && now - lastLocationSentAt < 30000) return

    send({
      type: 'client_location_update',
      location: payload.location,
      name: payload.name || '当前位置',
      source: payload.source || 'browser',
      accuracy: payload.accuracy || null,
      timestamp: payload.timestamp || Date.now()
    })
    lastLocationSentAt = now
  }

  return {
    ws,
    sessionId,
    sessionCreated,
    latestLocationPayload,
    isConnected,
    connect,
    disconnect,
    send,
    ensureSessionCreated,
    sendLocationUpdate,
    setOnMessage,
    setOnOpen,
    setOnClose
  }
}
