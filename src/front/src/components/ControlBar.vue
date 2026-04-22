<template>
  <div class="controls">
    <button
      class="btn-primary voice-btn"
      :class="{ recording: isRecording }"
      @click="$emit('toggle-voice')"
    >{{ isRecording ? '🔴 语音对话中' : '🎤 开始语音对话' }}</button>
    <button
      class="btn-primary video-btn"
      :class="{ 'recording-video': isRecordingVideo }"
      @click="$emit('toggle-video')"
    >{{ isRecordingVideo ? '🔴 停止视频采集' : '📹 开始视频采集' }}</button>
    <button class="btn-secondary disconnect-btn" @click="$emit('disconnect')">❌ 断开连接</button>
  </div>
</template>

<script>
export default {
  name: 'ControlBar',
  props: {
    isRecording: { type: Boolean, default: false },
    isRecordingVideo: { type: Boolean, default: false }
  },
  emits: ['toggle-voice', 'toggle-video', 'disconnect']
}
</script>
