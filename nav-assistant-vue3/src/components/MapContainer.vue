<template>
  <div
    id="mapContainer"
    class="map-container"
    :style="{ display: visible ? 'block' : 'none' }"
  >
    <div id="mapInner" class="map-inner"></div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const visible = ref(false)

defineExpose({ visible })
</script>

<style scoped>
.map-container {
  width: 100%;
  height: 420px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  margin: 0.75rem 0;
  position: relative;
  overflow: hidden;
}
.map-inner {
  width: 100%;
  height: 100%;
}
</style>
