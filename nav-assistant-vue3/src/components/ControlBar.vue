<template>
  <div class="controls">
    <button
      class="btn btn-primary"
      :class="{ 'btn-recording': audio.isRecording.value }"
      :disabled="!session.hasAvailableModel"
      @click="toggleVoice"
    >
      {{ audio.isRecording.value ? '🔴 语音对话中' : '🎤 开始语音对话' }}
    </button>

    <button
      class="btn btn-primary"
      :class="{ 'btn-recording': video.isRecordingVideo.value }"
      @click="toggleVideo"
    >
      {{ video.isRecordingVideo.value ? '🔴 停止视频采集' : '📹 开始视频采集' }}
    </button>

    <button class="btn btn-secondary" @click="handleDisconnect">
      ❌ 断开连接
    </button>
  </div>
</template>

<script setup>
import { useSessionStore } from '../stores/session'
import { useMessageStore } from '../stores/messages'

const props = defineProps({
  audio: Object,
  video: Object,
  wsManager: Object,
})

const session = useSessionStore()
const messages = useMessageStore()

const { audio, video, wsManager } = props

function showError(msg) {
  messages.addMessage('System', msg)
}

async function toggleVoice() {
  if (!audio.isRecording.value) {
    try {
      if (!session.instructions.trim()) { showError('⚠️ 系统指令不能为空'); return }
      if (!session.isConnected) { showError('⚠️ WebSocket 尚未连接'); return }
      await wsManager.ensureSessionCreated()
      await audio.startRecording()
    } catch (err) {
      showError('⚠️ ' + err.message)
    }
  } else {
    audio.stopRecording()
  }
}

async function toggleVideo() {
  if (!video.isRecordingVideo.value) {
    try {
      const videoEl = document.getElementById('videoPreview')
      await wsManager.ensureSessionCreated()
      await video.startVideoRecording(videoEl)
    } catch (err) {
      showError('⚠️ ' + err.message)
    }
  } else {
    video.stopVideoRecording()
  }
}

function handleDisconnect() {
  audio.stopRecording()
  video.stopVideoRecording()
  audio.stopPlayback()
  wsManager.disconnect()
}
</script>

<style scoped>
.controls {
  display: flex;
  gap: 0.75rem;
  align-items: center;
}
.controls .btn:first-child,
.controls .btn:nth-child(2) {
  flex: 1;
}
.controls .btn:last-child {
  width: 140px;
  flex-shrink: 0;
}
@media (max-width: 760px) {
  .controls { flex-wrap: wrap; }
  .controls .btn { width: 100% !important; flex: auto !important; }
}
</style>
