import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useMessageStore = defineStore('messages', () => {
  const messages = ref([])

  // Streaming transcript state
  const currentTranscript = ref('')
  const currentTranscriptSender = ref('')
  const currentResponseTranscript = ref('')
  const currentResponseSender = ref('')

  function addMessage(sender, text) {
    messages.value.unshift({
      id: Date.now() + Math.random(),
      sender,
      text,
      time: new Date().toLocaleTimeString(),
    })
  }

  function appendTranscript(sender, delta) {
    currentTranscriptSender.value = sender
    currentTranscript.value += delta
  }

  function finishTranscript() {
    if (currentTranscript.value) {
      addMessage(currentTranscriptSender.value, currentTranscript.value)
    }
    currentTranscript.value = ''
    currentTranscriptSender.value = ''
  }

  function appendResponseTranscript(sender, delta) {
    currentResponseSender.value = sender
    currentResponseTranscript.value += delta
  }

  function finishResponseTranscript() {
    if (currentResponseTranscript.value) {
      addMessage(currentResponseSender.value, currentResponseTranscript.value)
    }
    currentResponseTranscript.value = ''
    currentResponseSender.value = ''
  }

  return {
    messages,
    currentTranscript, currentTranscriptSender,
    currentResponseTranscript, currentResponseSender,
    addMessage, appendTranscript, finishTranscript,
    appendResponseTranscript, finishResponseTranscript,
  }
})
