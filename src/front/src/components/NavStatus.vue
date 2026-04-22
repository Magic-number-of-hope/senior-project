<template>
  <div class="nav-status" :class="{ active: visible }">
    <span class="spinner"></span>
    <span>{{ statusText }}</span>
  </div>
</template>

<script>
import { ref } from 'vue'

export default {
  name: 'NavStatus',
  setup () {
    const visible = ref(false)
    const statusText = ref('正在分析导航意图...')

    function updateNavStatus (state, text) {
      if (state === 'processing') {
        visible.value = true
        statusText.value = text || '正在分析...'
      } else if (state === 'done') {
        statusText.value = text || '完成'
        setTimeout(() => { visible.value = false }, 2000)
      } else if (state === 'error') {
        statusText.value = '❌ ' + (text || '出错')
        setTimeout(() => { visible.value = false }, 4000)
      } else {
        visible.value = false
      }
    }

    return { visible, statusText, updateNavStatus }
  }
}
</script>
