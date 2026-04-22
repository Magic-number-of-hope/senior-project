<template>
  <div class="text-input-container">
    <input
      type="text"
      ref="inputEl"
      v-model="text"
      placeholder="例如：从武汉理工到光谷广场，开车避堵"
      @input="updateState"
      @keypress.enter="onEnter"
    />
    <button
      class="btn-primary"
      :disabled="!canSend"
      @click="$emit('send', text); text = ''"
    >📤 发送</button>
  </div>
</template>

<script>
import { ref, computed } from 'vue'

export default {
  name: 'TextInput',
  props: {
    wsConnected: { type: Boolean, default: false }
  },
  emits: ['send'],
  setup (props, { emit }) {
    const text = ref('')
    const inputEl = ref(null)

    const canSend = computed(() => {
      return text.value.trim().length > 0 && props.wsConnected
    })

    function updateState () { /* computed handles reactivity */ }

    function onEnter () {
      if (!canSend.value) return
      emit('send', text.value)
      text.value = ''
    }

    function setText (val) {
      text.value = val
    }

    return { text, inputEl, canSend, updateState, onEnter, setText }
  }
}
</script>
