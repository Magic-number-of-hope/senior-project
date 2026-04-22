<template>
  <div class="messages-container" ref="messagesEl">
    <div v-if="messages.length === 0" class="messages-empty">
      <p class="messages-empty-title">对话将在这里展开</p>
      <p class="messages-empty-text">你可以直接输入导航指令，或使用上方语音、视频控制开始交互。</p>
    </div>

    <div
      v-for="(msg, idx) in messages"
      :key="idx"
      :class="['message', messageRoleClass(msg.sender)]"
    >
      <div class="message-meta">{{ msg.time }} · {{ msg.sender }}</div>
      <template v-if="msg.isHtml">
        <pre v-if="msg.hasNewline" class="message-pre">{{ msg.text }}</pre>
        <p v-else class="message-text">{{ msg.text }}</p>
      </template>
      <template v-else>
        <p class="message-text">{{ msg.text }}</p>
      </template>
    </div>
  </div>
</template>

<script>
import { ref, nextTick } from 'vue'

export default {
  name: 'MessageList',
  setup () {
    const messagesEl = ref(null)
    const messages = ref([])

    function messageRoleClass (sender) {
      if (!sender) return 'is-system'
      if (sender.startsWith('You')) return 'is-user'
      if (sender === 'System') return 'is-system'
      if (sender === 'Error') return 'is-error'
      return 'is-assistant'
    }

    function scrollToBottom () {
      if (!messagesEl.value) return
      messagesEl.value.scrollTop = messagesEl.value.scrollHeight
    }

    function addMessage (sender, text) {
      const time = new Date().toLocaleTimeString()
      const hasNewline = text.includes('\n')
      messages.value.push({
        sender,
        text,
        time,
        hasNewline,
        isHtml: true
      })
      nextTick(scrollToBottom)
    }

    return {
      messagesEl,
      messages,
      messageRoleClass,
      addMessage
    }
  }
}
</script>
