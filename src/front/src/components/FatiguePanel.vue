<template>
  <div class="fatigue-panel">
    <div class="fatigue-header">
      <span class="fatigue-title">驾驶状态评估</span>
      <span
        class="fatigue-badge"
        :class="fatigueState.level"
      >{{ fatigueState.level }}</span>
    </div>
    <div class="fatigue-grid">
      <div class="fatigue-cell">
        <strong>置信度</strong>
        <span>{{ Math.round(fatigueState.confidence * 100) }}%</span>
      </div>
      <div class="fatigue-cell">
        <strong>采样率</strong>
        <span>{{ currentVideoFps }} fps</span>
      </div>
      <div class="fatigue-cell">
        <strong>视觉信号</strong>
        <span>低头{{ Math.round(fatigueState.headDownRatio * 100) }}% / 无脸{{ Math.round(fatigueState.noFaceRatio * 100) }}%</span>
      </div>
      <div class="fatigue-cell">
        <strong>行为信号</strong>
        <span>延迟 {{ Math.round(fatigueState.behaviorScore * 3500 + 1500) }}ms</span>
      </div>
    </div>
    <div class="fatigue-safety-note">AI 仅辅助提醒，不构成医学或安全判定。</div>
  </div>
</template>

<script>
export default {
  name: 'FatiguePanel',
  props: {
    fatigueState: {
      type: Object,
      required: true
    },
    currentVideoFps: {
      type: Number,
      default: 1
    }
  }
}
</script>
