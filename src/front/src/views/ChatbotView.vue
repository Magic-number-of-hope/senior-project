<template>
  <div class="chatbot-shell">
    <header class="app-header">
      <div class="brand-cluster">
        <div class="brand-mark">导</div>
        <div class="brand-copy">
          <p class="brand-kicker">Smart In-Car Navigation Console</p>
          <h1>小导 | 车载导航助手</h1>
          <p class="hero-subtitle">支持语音和文本输入，自动完成意图识别、槽位提取、POI 检索与路线规划。</p>
        </div>
      </div>

      <div class="header-meta">
        <div class="status-pills">
          <span class="status-pill" :class="wsConnected ? 'online' : 'offline'">
            {{ wsConnected ? '连接正常' : '连接中断' }}
          </span>
          <span class="status-pill" :class="sessionCreated ? 'online' : 'muted'">
            {{ sessionCreated ? '会话已创建' : '待创建会话' }}
          </span>
        </div>
        <button class="btn-secondary header-config-btn" @click="toggleConfigPanel">
          {{ showConfigPanel ? '收起设置' : '会话设置' }}
        </button>
      </div>
    </header>

    <section v-show="showConfigPanel" class="config-drawer">
      <ConfigPanel ref="configPanelRef" @voice-disabled="onVoiceDisabled" />
    </section>

    <div v-if="errorMsg" class="error-message app-alert">{{ errorMsg }}</div>

    <main class="dashboard-layout">
      <section class="stage-panel">
        <div class="stage-map-card panel-card">
          <div class="panel-heading">
            <div>
              <p class="panel-eyebrow">Map</p>
              <h2>导航画布</h2>
            </div>
            <p class="panel-caption">路线、候选点与途经点会实时绘制在地图上。</p>
          </div>
          <MapContainer
            ref="mapContainerRef"
            :map-status="mapStatus"
            :map-status-message="mapStatusMessage"
          />
        </div>

        <div class="stage-info-stack">
          <IntentPanel
            ref="intentPanelRef"
            @message="onIntentMessage"
            @slot-fill="onSlotFill"
            @poi-select="onPoiSelect"
          />
          <FatiguePanel :fatigue-state="fatigueState" :current-video-fps="currentVideoFps" />
          <NavStatus ref="navStatusRef" />
        </div>
      </section>

      <aside class="assistant-sidebar">
        <div class="chat-card panel-card">
          <div class="chat-card-header">
            <div class="chat-card-header-main">
              <div>
                <p class="panel-eyebrow">Conversation</p>
                <h2>对话面板</h2>
              </div>
              <div class="chat-header-status">
                <span class="chat-dot" :class="{ online: wsConnected }"></span>
                <span>{{ wsConnected ? '在线' : '离线' }}</span>
              </div>
            </div>

            <div class="chat-card-toolbar">
              <ControlBar
                class="chat-controls"
                :is-recording="isRecording"
                :is-recording-video="isRecordingVideo"
                @toggle-voice="toggleVoice"
                @toggle-video="toggleVideo"
                @disconnect="handleDisconnect"
              />
            </div>
          </div>

          <div class="chat-card-body">
            <MessageList ref="messageListRef" />
          </div>

          <div class="chat-card-footer">
            <TextInput ref="textInputRef" :ws-connected="wsConnected" @send="onSendText" />
          </div>
        </div>
      </aside>
    </main>

    <div class="video-float" :class="{ active: isRecordingVideo }">
      <div class="video-float-head">
        <span>前置视频</span>
        <span>{{ isRecordingVideo ? '采集中' : '未开启' }}</span>
      </div>
      <video
        ref="videoPreviewRef"
        autoplay muted playsinline
        class="video-preview"
        :class="{ active: isRecordingVideo }"
        id="videoPreview"
      ></video>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, onBeforeUnmount } from 'vue'

import ConfigPanel from '../components/ConfigPanel.vue'
import ControlBar from '../components/ControlBar.vue'
import FatiguePanel from '../components/FatiguePanel.vue'
import MessageList from '../components/MessageList.vue'
import TextInput from '../components/TextInput.vue'
import NavStatus from '../components/NavStatus.vue'
import MapContainer from '../components/MapContainer.vue'
import IntentPanel from '../components/IntentPanel.vue'

import { useWebSocket } from '../composables/useWebSocket'
import { useAudio } from '../composables/useAudio'
import { useVideo } from '../composables/useVideo'
import { useLocation } from '../composables/useLocation'
import { useAmap } from '../composables/useAmap'

export default {
  name: 'ChatbotView',
  components: {
    ConfigPanel,
    ControlBar,
    FatiguePanel,
    MessageList,
    TextInput,
    NavStatus,
    MapContainer,
    IntentPanel
  },
  setup () {
    /* ═══ 组件引用 ═══ */
    const configPanelRef = ref(null)
    const textInputRef = ref(null)
    const messageListRef = ref(null)
    const navStatusRef = ref(null)
    const mapContainerRef = ref(null)
    const intentPanelRef = ref(null)
    const videoPreviewRef = ref(null)

    /* ═══ 局部 UI 状态 ═══ */
    const errorMsg = ref('')
    const wsConnected = ref(false)
    const showConfigPanel = ref(false)
    let errorTimer = null

    /* ── 消息 / 错误辅助 ── */
    function addMessage (sender, text) {
      messageListRef.value?.addMessage(sender, text)
    }

    function showError (msg) {
      errorMsg.value = msg
      if (errorTimer) clearTimeout(errorTimer)
      errorTimer = setTimeout(() => { errorMsg.value = '' }, 5000)
    }

    function toggleConfigPanel () {
      showConfigPanel.value = !showConfigPanel.value
    }

    /* ═══ 初始化 Composables ═══ */
    const {
      sessionId, sessionCreated, latestLocationPayload,
      isConnected, connect, disconnect: wsDisconnect, send,
      ensureSessionCreated, sendLocationUpdate,
      setOnMessage, setOnOpen, setOnClose
    } = useWebSocket()

    const {
      isRecording,
      startRecording, stopRecording,
      queueAudioChunk, stopAudioPlayback
    } = useAudio(send, isConnected)

    const {
      isRecordingVideo, currentVideoFps, fatigueState,
      initFaceDetector, startVideoRecording, stopVideoRecording,
      onUserInputCommitted, onAgentResponseStarted
    } = useVideo(send, isConnected, sessionCreated, sessionId, addMessage)

    const {
      amapReady, mapStatus, mapStatusMessage, selectedRouteIndex,
      initAMap, setMapContainer,
      showRouteOnMap, showCandidatesOnMap,
      planRouteByJsApiOnce, sendPlannedRouteToBackend,
      getRouteOptions, destroyMap
    } = useAmap(send, isConnected)

    const { tryUploadCurrentLocation } = useLocation(
      sendLocationUpdate,
      () => amapReady.value
    )

    /* ═══ 转写流式累积 ═══ */
    let currentTranscript = ''
    let currentTranscriptMsg = null
    let currentResponseTranscript = ''
    let currentResponseTranscriptMsg = null

    function appendTranscript (sender, text) {
      if (!currentTranscriptMsg) {
        currentTranscript = ''
        addMessage(sender, '')
        const msgs = messageListRef.value?.messages
        if (msgs && msgs.length > 0) {
          currentTranscriptMsg = msgs[msgs.length - 1]
        }
      }
      currentTranscript += text
      if (currentTranscriptMsg) {
        currentTranscriptMsg.text = currentTranscript
      }
    }

    function finishTranscript () {
      currentTranscript = ''
      currentTranscriptMsg = null
    }

    function appendResponseTranscript (sender, text) {
      if (!currentResponseTranscriptMsg) {
        currentResponseTranscript = ''
        addMessage(sender, '')
        const msgs = messageListRef.value?.messages
        if (msgs && msgs.length > 0) {
          currentResponseTranscriptMsg = msgs[msgs.length - 1]
        }
      }
      currentResponseTranscript += text
      if (currentResponseTranscriptMsg) {
        currentResponseTranscriptMsg.text = currentResponseTranscript
      }
    }

    function finishResponseTranscript () {
      currentResponseTranscript = ''
      currentResponseTranscriptMsg = null
    }

    /* ═══ WebSocket 回调 ═══ */
    setOnOpen(() => {
      wsConnected.value = true
      addMessage('System', '✅ WebSocket connected successfully, ready for voice conversation')
      tryUploadCurrentLocation(false)
    })

    setOnClose(() => {
      wsConnected.value = false
      addMessage('System', '❌ Disconnected')
      stopRecording(sessionId)
      stopVideoRecording(videoPreviewRef.value)
    })

    /* ── WebSocket 消息路由（对应 chatbot.html 的 switch/case） ── */
    setOnMessage(async (data) => {
      switch (data.type) {
        case 'server_session_created':
          sessionCreated.value = true
          addMessage('System', `✅ Session created: ${data.session_id}`)
          if (latestLocationPayload.value) {
            sendLocationUpdate(latestLocationPayload.value, true)
          } else {
            tryUploadCurrentLocation(true)
          }
          break

        case 'agent_ready':
          addMessage('System', `🤖 Agent ${data.agent_name} is ready`)
          break

        case 'agent_response_created':
          onAgentResponseStarted()
          addMessage('System', `💬 Agent ${data.agent_name} started generating response...`)
          break

        case 'agent_response_audio_delta':
          queueAudioChunk(data.delta)
          break

        case 'agent_response_audio_done':
          addMessage('System', '🔊 Audio response completed')
          break

        case 'agent_response_audio_transcript_delta':
          onAgentResponseStarted()
          appendResponseTranscript(data.agent_name, data.delta || '')
          break

        case 'agent_response_audio_transcript_done':
          finishResponseTranscript()
          break

        case 'agent_input_transcription_delta':
          appendTranscript('You', data.delta || '')
          break

        case 'agent_input_transcription_done':
          appendTranscript('You', data.transcript || '')
          finishTranscript()
          onUserInputCommitted()
          addMessage('System', '📝 User input recognition completed')
          break

        case 'agent_input_started':
          addMessage('System', '🎤 Voice input started')
          break

        case 'agent_input_done':
          addMessage('System', '⏹️ Voice input ended')
          break

        case 'agent_response_done':
          addMessage('System', `✅ Response completed (input tokens: ${data.input_tokens}, output tokens: ${data.output_tokens})`)
          break

        case 'agent_response_tool_use_delta':
          addMessage('System', `🔧 Tool call: ${data.name}`)
          break

        case 'agent_response_tool_use_done': {
          const toolUseInfo = JSON.stringify(data.tool_use, null, 2)
          addMessage(data.agent_name, `🔧 Tool Use:\n${toolUseInfo}`)
          break
        }

        case 'agent_response_tool_result': {
          const toolResultInfo = JSON.stringify(data.tool_result, null, 2)
          addMessage(data.agent_name, `✅ Tool Result:\n${toolResultInfo}`)
          break
        }

        case 'agent_error':
          addMessage('Error', `❌ ${data.error_type}: ${data.message}`)
          break

        case 'agent_ended':
          addMessage('System', `👋 Agent ${data.agent_name} has ended`)
          break

        case 'server_session_ended':
          addMessage('System', `🔚 Session ${data.session_id} has ended`)
          break

        case 'whisper_transcription': {
          const whisperText = (data.transcript || '').trim()
          if (whisperText) {
            textInputRef.value?.setText(whisperText)
            addMessage('You (Whisper)', whisperText)
          }
          addMessage('System', '📝 Whisper 语音转写完成，已填入输入框')
          break
        }

        case 'visual_analysis_result':
          addMessage('视觉分析', '👁️ ' + (data.description || ''))
          break

        // ── 导航事件 ──
        case 'nav_status_update':
          navStatusRef.value?.updateNavStatus(data.status, data.message)
          if (data.status === 'processing') {
            addMessage('System', '🔄 ' + (data.message || '导航分析中...'))
          }
          break

        case 'nav_intent_result':
          intentPanelRef.value?.renderIntentPanel(data.intent_result)
          navStatusRef.value?.updateNavStatus('done', '意图分析完成')
          break

        case 'nav_route_result': {
          const jsPlannedRoute = await planRouteByJsApiOnce(data.route_result || {})
          const routeOpts = getRouteOptions(jsPlannedRoute)
          const selIdx = selectedRouteIndex.value || 0
          intentPanelRef.value?.renderRouteResult(jsPlannedRoute, routeOpts, selIdx)
          await showRouteOnMap(jsPlannedRoute, mapContainerRef.value?.routeOptionsEl)
          sendPlannedRouteToBackend(jsPlannedRoute)
          navStatusRef.value?.updateNavStatus('done', '路线规划完成')
          break
        }

        case 'nav_poi_candidates':
          intentPanelRef.value?.renderPOICandidates(
            data.candidates,
            data.origin_candidates,
            data.destination_candidates
          )
          showCandidatesOnMap(data.candidates || [])
          break

        case 'nav_missing_slots':
          intentPanelRef.value?.renderMissingSlots(data.missing, data.current_slots)
          break

        case 'nav_error':
          navStatusRef.value?.updateNavStatus('error', data.message || '导航出错')
          addMessage('System', '❌ ' + (data.message || '导航分析失败'))
          break

        default:
          console.log('Unhandled event type:', data.type)
          break
      }
    })

    /* ═══ 用户交互 ═══ */
    async function toggleVoice () {
      if (!isRecording.value) {
        await startVoice()
      } else {
        stopRecording(sessionId)
        addMessage('System', '⏹️ Voice chat stopped')
      }
    }

    async function startVoice () {
      try {
        const cfg = configPanelRef.value
        if (!cfg) return

        const instructions = (cfg.instructions || '').trim()
        if (!instructions) {
          showError('⚠️ 系统指令不能为空！请在开始语音对话前输入系统指令。')
          return
        }
        if (!isConnected()) {
          showError('⚠️ WebSocket 尚未连接！请等待连接。')
          return
        }

        await ensureSessionCreated(
          instructions,
          cfg.agentName || '小导',
          cfg.modelProvider || 'dashscope'
        )

        await startRecording(sessionId)
        addMessage('System', '🎤 Voice chat started...')
      } catch (err) {
        console.error('Failed to start recording:', err)
        showError('⚠️ ' + err.message)
        addMessage('System', '⚠️ ' + err.message)
      }
    }

    async function toggleVideo () {
      if (!isRecordingVideo.value) {
        if (!isConnected()) {
          showError('⚠️ WebSocket 尚未连接！')
          return
        }
        if (!sessionCreated.value) {
          showError('⚠️ 会话尚未创建！请先开始语音对话。')
          return
        }
        await startVideoRecording(videoPreviewRef.value)
      } else {
        stopVideoRecording(videoPreviewRef.value)
      }
    }

    function handleDisconnect () {
      stopRecording(sessionId)
      stopVideoRecording(videoPreviewRef.value)
      stopAudioPlayback()
      wsDisconnect()
    }

    async function onSendText (text) {
      if (!text || !text.trim()) return
      text = text.trim()

      if (!isConnected()) {
        showError('⚠️ WebSocket is not connected!')
        return
      }

      try {
        tryUploadCurrentLocation(true)
        const cfg = configPanelRef.value
        await ensureSessionCreated(
          (cfg?.instructions || '').trim(),
          cfg?.agentName || '小导',
          cfg?.modelProvider || 'dashscope'
        )
      } catch (err) {
        showError('⚠️ ' + err.message)
        addMessage('System', '⚠️ ' + err.message)
        return
      }

      send({
        type: 'client_text_append',
        session_id: sessionId,
        text
      })

      onUserInputCommitted()
      addMessage('You', text)
    }

    function onIntentMessage ({ sender, text }) {
      addMessage(sender, text)
    }

    function onSlotFill (filled) {
      if (isConnected()) {
        send({ type: 'nav_slot_fill', slots: filled })
      }
    }

    function onPoiSelect ({ index, poi }) {
      if (isConnected()) {
        send({ type: 'nav_poi_select', index, poi })
      }
    }

    function onVoiceDisabled () {
      showError('⚠️ 没有可用的模型 API Key，请配置后再使用语音功能。')
    }

    /* ═══ 生命周期 ═══ */
    onMounted(async () => {
      initFaceDetector()
      if (configPanelRef.value) {
        await configPanelRef.value.checkAvailableModels()
      }
      await initAMap()
      if (mapContainerRef.value) {
        setMapContainer(
          mapContainerRef.value.mapContainerEl,
          mapContainerRef.value.mapInnerEl
        )
      }
      connect()
    })

    onBeforeUnmount(() => {
      destroyMap()
      handleDisconnect()
      if (errorTimer) clearTimeout(errorTimer)
    })

    /* ═══ 模板绑定 ═══ */
    return {
      configPanelRef,
      textInputRef,
      messageListRef,
      navStatusRef,
      mapContainerRef,
      intentPanelRef,
      videoPreviewRef,
      errorMsg,
      wsConnected,
      sessionCreated,
      showConfigPanel,
      isRecording,
      isRecordingVideo,
      fatigueState,
      currentVideoFps,
      mapStatus,
      mapStatusMessage,
      toggleConfigPanel,
      toggleVoice,
      toggleVideo,
      handleDisconnect,
      onSendText,
      onIntentMessage,
      onSlotFill,
      onPoiSelect,
      onVoiceDisabled
    }
  }
}
</script>
