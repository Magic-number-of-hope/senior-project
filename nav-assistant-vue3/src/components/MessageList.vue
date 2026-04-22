<template>
  <div class="messages-container card" ref="containerRef">
    <!-- Streaming response transcript -->
    <div v-if="msgStore.currentResponseTranscript" class="message streaming">
      <strong>[{{ now }}] {{ msgStore.currentResponseSender }}:</strong>
      <span class="transcript-text">{{ msgStore.currentResponseTranscript }}</span>
      <span class="typing-indicator">▊</span>
    </div>

    <!-- Streaming user transcript -->
    <div v-if="msgStore.currentTranscript" class="message streaming">
      <strong>[{{ now }}] {{ msgStore.currentTranscriptSender }}:</strong>
      <span class="transcript-text">{{ msgStore.currentTranscript }}</span>
      <span class="typing-indicator">▊</span>
    </div>

    <!-- Message history -->
    <div
      v-for="msg in msgStore.messages"
      :key="msg.id"
      class="message"
      :class="messageClass(msg.sender)"
    >
      <strong>[{{ msg.time }}] {{ msg.sender }}:</strong>
      <pre v-if="msg.text.includes('\n')" class="message-pre">{{ msg.text }}</pre>
      <span v-else> {{ msg.text }}</span>
    </div>

    <div v-if="msgStore.messages.length === 0 && !msgStore.currentTranscript && !msgStore.currentResponseTranscript" class="empty-hint">
      暂无消息
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useMessageStore } from '../stores/messages'

const msgStore = useMessageStore()

const now = computed(() => new Date().toLocaleTimeString())

function messageClass(sender) {
  if (sender === 'Error') return 'msg-error'
  if (sender === 'System') return 'msg-system'
  if (sender === 'You' || sender.startsWith('You')) return 'msg-user'
  return 'msg-agent'
}
</script>

<style scoped>
.messages-container {
  min-height: 300px;
  max-height: 500px;
  overflow-y: auto;
  padding: 1rem;
  flex: 1;
}
.message {
  margin: 0.5rem 0;
  padding: 0.625rem 0.875rem;
  background: var(--bg-card);
  border-radius: var(--radius);
  border: 1px solid var(--border);
  font-size: 0.8125rem;
  word-break: break-word;
}
.message strong {
  color: var(--text-secondary);
  font-weight: 600;
}
.msg-error {
  background: hsl(0, 84.2%, 95%);
  border-color: hsl(0, 84.2%, 85%);
}
.msg-user strong { color: var(--brand); }
.msg-agent strong { color: var(--blue); }
.streaming {
  border-color: var(--blue);
  background: var(--blue-bg);
}
.typing-indicator {
  animation: blink 1s step-end infinite;
  color: var(--blue);
}
@keyframes blink { 50% { opacity: 0; } }
.message-pre {
  margin: 0.375rem 0;
  padding: 0.5rem;
  background: var(--bg-muted);
  border-radius: 0.25rem;
  overflow-x: auto;
  font-size: 0.75rem;
  white-space: pre-wrap;
  font-family: 'Menlo', 'Consolas', monospace;
}
.empty-hint {
  text-align: center;
  color: var(--text-muted);
  padding: 3rem 0;
  font-size: 0.875rem;
}
</style>
