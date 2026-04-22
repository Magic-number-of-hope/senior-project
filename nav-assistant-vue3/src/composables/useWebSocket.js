import { useSessionStore } from '../stores/session'
import { useMessageStore } from '../stores/messages'
import { useNavStore } from '../stores/nav'

export function useWebSocket() {
  const session = useSessionStore()
  const messages = useMessageStore()
  const nav = useNavStore()

  let onRouteResult = null
  let onPOICandidates = null

  function setRouteResultHandler(fn) { onRouteResult = fn }
  function setPOICandidatesHandler(fn) { onPOICandidates = fn }

  async function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/You/${session.sessionId}`

    const ws = new WebSocket(wsUrl)
    session.setWs(ws)

    ws.onopen = () => {
      messages.addMessage('System', '✅ WebSocket 连接成功，准备就绪')
      tryUploadCurrentLocation(false)
    }

    ws.onmessage = async (event) => {
      try {
        const data = JSON.parse(event.data)
        handleMessage(data)
      } catch (e) {
        console.error('Error processing message:', e)
      }
    }

    ws.onclose = () => {
      messages.addMessage('System', '❌ 连接已断开')
      session.setSessionCreated(false)
    }

    ws.onerror = () => {
      messages.addMessage('System', '⚠️ 连接错误')
    }
  }

  function handleMessage(data) {
    switch (data.type) {
      case 'server_session_created':
        session.setSessionCreated(true)
        messages.addMessage('System', `✅ 会话已创建: ${data.session_id}`)
        if (session.latestLocationPayload) {
          session.sendLocationUpdate(session.latestLocationPayload, true)
        } else {
          tryUploadCurrentLocation(true)
        }
        break

      case 'agent_ready':
        messages.addMessage('System', `🤖 智能体 ${data.agent_name} 已就绪`)
        break

      case 'agent_response_created':
        session.onAgentResponseStarted()
        messages.addMessage('System', `💬 ${data.agent_name} 正在生成回复...`)
        break

      case 'agent_response_audio_delta':
        if (window.__audioPlaybackCallback) window.__audioPlaybackCallback(data.delta)
        break

      case 'agent_response_audio_done':
        messages.addMessage('System', '🔊 语音回复完成')
        break

      case 'agent_response_audio_transcript_delta':
        session.onAgentResponseStarted()
        messages.appendResponseTranscript(data.agent_name, data.delta || '')
        break

      case 'agent_response_audio_transcript_done':
        messages.finishResponseTranscript()
        break

      case 'agent_input_transcription_delta':
        messages.appendTranscript('You', data.delta || '')
        break

      case 'agent_input_transcription_done':
        messages.appendTranscript('You', data.transcript || '')
        messages.finishTranscript()
        session.onUserInputCommitted()
        break

      case 'agent_input_started':
        messages.addMessage('System', '🎤 语音输入开始')
        break

      case 'agent_input_done':
        messages.addMessage('System', '⏹️ 语音输入结束')
        break

      case 'agent_response_done':
        messages.addMessage('System', `✅ 回复完成 (input: ${data.input_tokens}, output: ${data.output_tokens})`)
        break

      case 'agent_response_tool_use_delta':
        messages.addMessage('System', `🔧 调用工具: ${data.name}`)
        break

      case 'agent_response_tool_use_done':
        messages.addMessage(data.agent_name, `🔧 Tool Use:\n${JSON.stringify(data.tool_use, null, 2)}`)
        break

      case 'agent_response_tool_result':
        messages.addMessage(data.agent_name, `✅ Tool Result:\n${JSON.stringify(data.tool_result, null, 2)}`)
        break

      case 'agent_error':
        messages.addMessage('Error', `❌ ${data.error_type}: ${data.message}`)
        break

      case 'agent_ended':
        messages.addMessage('System', `👋 智能体 ${data.agent_name} 已结束`)
        break

      case 'server_session_ended':
        messages.addMessage('System', `🔚 会话 ${data.session_id} 已结束`)
        break

      case 'whisper_transcription': {
        const text = (data.transcript || '').trim()
        if (text && window.__whisperCallback) window.__whisperCallback(text)
        messages.addMessage('System', '📝 Whisper 语音转写完成')
        break
      }

      case 'visual_analysis_result':
        messages.addMessage('视觉分析', '👁️ ' + (data.description || ''))
        break

      case 'nav_status_update':
        nav.updateNavStatus(data.status, data.message)
        if (data.status === 'processing') {
          messages.addMessage('System', '🔄 ' + (data.message || '导航分析中...'))
        }
        break

      case 'nav_intent_result':
        nav.setIntentResult(data.intent_result)
        nav.updateNavStatus('done', '意图分析完成')
        break

      case 'nav_route_result':
        if (onRouteResult) onRouteResult(data.route_result)
        nav.updateNavStatus('done', '路线规划完成')
        break

      case 'nav_poi_candidates':
        nav.setPOICandidates(data.candidates, data.origin_candidates, data.destination_candidates)
        if (onPOICandidates) onPOICandidates(nav.poiCandidates)
        break

      case 'nav_missing_slots':
        nav.setMissingSlots(data.missing, data.current_slots)
        break

      case 'nav_error':
        nav.updateNavStatus('error', data.message || '导航出错')
        messages.addMessage('System', '❌ ' + (data.message || '导航分析失败'))
        break

      default:
        console.log('Unhandled event:', data.type)
    }
  }

  async function ensureSessionCreated() {
    if (session.sessionCreated) return

    if (!session.instructions.trim()) throw new Error('系统指令不能为空')
    if (!session.isConnected) throw new Error('WebSocket 尚未连接')

    messages.addMessage('System', '📝 正在创建会话...')
    session.sendMessage({
      type: 'client_session_create',
      config: {
        instructions: session.instructions,
        agent_name: session.agentName,
        model_provider: session.modelProvider,
      },
    })

    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('会话创建超时')), 5000)
      const check = setInterval(() => {
        if (session.sessionCreated) {
          clearTimeout(timeout)
          clearInterval(check)
          resolve()
        }
      }, 100)
    })
  }

  function disconnect() {
    if (session.ws) session.ws.close()
    session.setSessionCreated(false)
  }

  function tryUploadCurrentLocation(force) {
    if (window.AMap && window._amapReady) {
      try {
        const geolocation = new AMap.Geolocation({
          enableHighAccuracy: true, timeout: 8000, convert: true, showButton: false,
        })
        geolocation.getCurrentPosition((status, result) => {
          if (status === 'complete' && result?.position) {
            const payload = {
              location: `${Number(result.position.lng).toFixed(6)},${Number(result.position.lat).toFixed(6)}`,
              name: '当前位置',
              source: 'amap',
              accuracy: Math.round(result.accuracy || 0),
              timestamp: Date.now(),
            }
            session.sendLocationUpdate(payload, !!force)
            return
          }
          uploadBrowserLocation(force)
        })
        return
      } catch (err) {
        console.warn('[LOCATION] AMap geolocation failed, fallback browser:', err)
      }
    }
    uploadBrowserLocation(force)
  }

  function uploadBrowserLocation(force) {
    if (!navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const payload = {
          location: `${Number(pos.coords.longitude).toFixed(6)},${Number(pos.coords.latitude).toFixed(6)}`,
          name: '当前位置',
          source: 'browser',
          accuracy: Math.round(pos.coords.accuracy || 0),
          timestamp: pos.timestamp || Date.now(),
        }
        session.sendLocationUpdate(payload, !!force)
      },
      (err) => console.warn('[LOCATION] getCurrentPosition failed:', err?.message),
      { enableHighAccuracy: true, timeout: 6000, maximumAge: 120000 },
    )
  }

  return {
    connect, disconnect, ensureSessionCreated,
    tryUploadCurrentLocation,
    setRouteResultHandler, setPOICandidatesHandler,
  }
}
