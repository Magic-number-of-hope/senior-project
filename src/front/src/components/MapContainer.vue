<template>
  <div class="map-stage">
    <div ref="mapContainerEl" class="map-surface">
      <div ref="mapInnerEl" class="map-surface-inner"></div>
      <div class="map-surface-placeholder">{{ placeholderText }}</div>
    </div>
    <div ref="routeOptionsEl" class="route-options"></div>
  </div>
</template>

<script>
import { ref, computed } from 'vue'

export default {
  name: 'MapContainer',
  props: {
    mapStatus: {
      type: String,
      default: 'idle'
    },
    mapStatusMessage: {
      type: String,
      default: ''
    }
  },
  setup (props) {
    const mapContainerEl = ref(null)
    const mapInnerEl = ref(null)
    const routeOptionsEl = ref(null)
    const placeholderText = computed(() => {
      if (props.mapStatusMessage) return props.mapStatusMessage
      if (props.mapStatus === 'ready') return '等待路线或候选点绘制'
      return '等待地图初始化'
    })

    return {
      mapContainerEl,
      mapInnerEl,
      routeOptionsEl,
      placeholderText
    }
  }
}
</script>
