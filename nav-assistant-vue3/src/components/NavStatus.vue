<template>
  <Transition name="fade">
    <div v-if="nav.navStatus !== 'idle'" class="nav-status" :class="nav.navStatus">
      <span v-if="nav.navStatus === 'processing'" class="spinner"></span>
      <span>{{ statusText }}</span>
    </div>
  </Transition>
</template>

<script setup>
import { computed } from 'vue'
import { useNavStore } from '../stores/nav'

const nav = useNavStore()

const statusText = computed(() => {
  if (nav.navStatus === 'error') return '❌ ' + (nav.navStatusText || '出错')
  return nav.navStatusText || '正在分析...'
})
</script>

<style scoped>
.nav-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: var(--bg-muted);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  font-size: 0.8rem;
  color: var(--text-secondary);
}
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
