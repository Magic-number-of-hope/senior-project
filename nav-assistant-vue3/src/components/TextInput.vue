<template>
  <div>
    <div class="text-input-row">
      <input
        type="text"
        v-model="textValue"
        placeholder="例如：从武汉理工到光谷广场，开车避堵"
        @keypress.enter="send"
      />
      <button
        class="btn btn-primary"
        :disabled="!canSend"
        @click="send"
      >
        📤 发送
      </button>
    </div>

    <div class="quick-commands">
      <button
        v-for="cmd in QUICK_COMMANDS"
        :key="cmd.text"
        class="quick-chip"
        @click="sendQuick(cmd.text)"
      >
        {{ cmd.icon }} {{ cmd.label }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useSessionStore } from '../stores/session'
import { useMessageStore } from '../stores/messages'
import { QUICK_COMMANDS } from '../utils/constants'

const props = defineProps({ wsManager: Object })
const session = useSessionStore()
const messages = useMessageStore()

const textValue = ref('')

const canSend = computed(() => textValue.value.trim().length > 0 && session.isConnected)

async function send() {
  const text = textValue.value.trim()
  if (!text || !session.isConnected) return

  try {
    props.wsManager.tryUploadCurrentLocation(true)
    await props.wsManager.ensureSessionCreated()
  } catch (err) {
    messages.addMessage('System', '⚠️ ' + err.message)
    return
  }

  session.sendMessage({
    type: 'client_text_append',
    session_id: session.sessionId,
    text,
  })

  session.onUserInputCommitted()
  messages.addMessage('You', text)
  textValue.value = ''
}

async function sendQuick(text) {
  textValue.value = text
  await send()
}

// Expose for whisper callback
window.__whisperCallback = (text) => { textValue.value = text }
</script>

<style scoped>
.text-input-row {
  display: flex;
  gap: 0.75rem;
  align-items: center;
}
.text-input-row input { flex: 1; }
.text-input-row .btn { width: 100px; flex-shrink: 0; }

.quick-commands {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-top: 0.75rem;
}
.quick-chip {
  border: 1px dashed #9fb3c0;
  background: #f4f8fb;
  color: #0f3748;
  padding: 0.45rem 0.75rem;
  border-radius: 999px;
  cursor: pointer;
  font-size: 0.8rem;
  transition: all 0.15s ease;
  font-family: inherit;
}
.quick-chip:hover {
  border-color: var(--brand);
  background: #e7f4f2;
  color: #0a4a45;
}

@media (max-width: 760px) {
  .text-input-row {
    flex-direction: column;
    align-items: stretch;
  }
  .text-input-row .btn { width: 100%; }
}
</style>
