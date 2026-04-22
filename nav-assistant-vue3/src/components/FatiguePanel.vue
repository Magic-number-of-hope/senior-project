<template>
  <div class="fatigue-panel card">
    <div class="fatigue-header">
      <span class="fatigue-title">驾驶状态评估</span>
      <span class="fatigue-badge" :class="fatigue.state.level">
        {{ fatigue.state.level }}
      </span>
    </div>
    <div class="fatigue-grid">
      <div class="fatigue-cell">
        <strong>置信度</strong>
        <span>{{ Math.round(fatigue.state.confidence * 100) }}%</span>
      </div>
      <div class="fatigue-cell">
        <strong>采样率</strong>
        <span>{{ fatigue.currentVideoFps }} fps</span>
      </div>
      <div class="fatigue-cell">
        <strong>视觉信号</strong>
        <span>低头{{ Math.round(fatigue.state.headDownRatio * 100) }}% / 无脸{{ Math.round(fatigue.state.noFaceRatio * 100) }}%</span>
      </div>
      <div class="fatigue-cell">
        <strong>行为信号</strong>
        <span>延迟 {{ Math.round(session.emaResponseLatencyMs || 0) }}ms</span>
      </div>
    </div>
    <div class="fatigue-note">AI 仅辅助提醒，不构成医学或安全判定。</div>
  </div>
</template>

<script setup>
import { useFatigueStore } from '../stores/fatigue'
import { useSessionStore } from '../stores/session'

const fatigue = useFatigueStore()
const session = useSessionStore()
</script>

<style scoped>
.fatigue-panel { padding: 0.85rem 1rem; }
.fatigue-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.6rem;
}
.fatigue-title { font-size: 0.9rem; font-weight: 700; color: #134252; }
.fatigue-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.2rem 0.65rem;
  font-size: 0.75rem;
  font-weight: 700;
}
.fatigue-badge.normal { background: #ddf6ea; color: #0a5f42; }
.fatigue-badge.attention { background: #fff2cf; color: #8a5200; }
.fatigue-badge.drowsy { background: #ffe0df; color: #a12929; }
.fatigue-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.45rem 0.8rem;
  font-size: 0.8rem;
  color: #284456;
}
.fatigue-cell strong { color: #123446; margin-right: 0.35rem; }
.fatigue-note {
  margin-top: 0.65rem;
  font-size: 0.74rem;
  color: #6e5a1c;
  background: #fff9e8;
  border: 1px dashed #e5cb7a;
  border-radius: 0.4rem;
  padding: 0.4rem 0.55rem;
}
</style>
