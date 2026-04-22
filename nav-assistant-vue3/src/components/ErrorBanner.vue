<template>
  <Transition name="slide">
    <div v-if="visible" class="error-banner">
      {{ message }}
    </div>
  </Transition>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({ message: String })
const visible = ref(false)

watch(() => props.message, (val) => {
  if (val) {
    visible.value = true
    setTimeout(() => { visible.value = false }, 5000)
  }
})
</script>

<style scoped>
.error-banner {
  padding: 0.875rem 1rem;
  background: hsl(0, 84.2%, 95%);
  border: 1px solid hsl(0, 84.2%, 85%);
  border-radius: var(--radius);
  color: hsl(0, 84.2%, 30%);
  font-size: 0.875rem;
  font-weight: 500;
  box-shadow: var(--shadow-sm);
}
.slide-enter-active, .slide-leave-active {
  transition: all 0.3s ease;
}
.slide-enter-from, .slide-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
