import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import { FATIGUE } from '../utils/constants'

export const useFatigueStore = defineStore('fatigue', () => {
  const state = reactive({
    level: 'normal',
    confidence: 0,
    visualScore: 0,
    behaviorScore: 0,
    fusionScore: 0,
    headDownRatio: 0,
    noFaceRatio: 0,
  })

  const currentVideoFps = ref(FATIGUE.NORMAL_FPS)
  const highFpsUntil = ref(0)
  const attentionStartTs = ref(null)
  const drowsyStartTs = ref(null)
  const lastRiskLevel = ref('normal')
  const visualWindow = ref([])

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value))
  }

  function computeBehaviorScore(emaResponseLatencyMs) {
    if (!emaResponseLatencyMs) return 0
    return clamp((emaResponseLatencyMs - 1500) / 3500, 0, 1)
  }

  function evaluate(nowTs, emaResponseLatencyMs) {
    const recent = visualWindow.value.filter(item => nowTs - item.ts <= 20000)
    visualWindow.value = recent

    let headDownRatio = 0
    let noFaceRatio = 0
    if (recent.length > 0) {
      headDownRatio = recent.filter(x => x.headDown).length / recent.length
      noFaceRatio = recent.filter(x => !x.facePresent).length / recent.length
    }

    const visualScore = clamp(0.65 * headDownRatio + 0.35 * noFaceRatio, 0, 1)
    const behaviorScore = computeBehaviorScore(emaResponseLatencyMs)
    const fusionScore = clamp(0.65 * visualScore + 0.35 * behaviorScore, 0, 1)

    let candidate = 'normal'
    if (fusionScore >= FATIGUE.DROWSY_SCORE) candidate = 'drowsy'
    else if (fusionScore >= FATIGUE.ATTENTION_SCORE) candidate = 'attention'

    if (candidate === 'drowsy') {
      drowsyStartTs.value = drowsyStartTs.value || nowTs
      attentionStartTs.value = attentionStartTs.value || nowTs
    } else if (candidate === 'attention') {
      attentionStartTs.value = attentionStartTs.value || nowTs
      drowsyStartTs.value = null
    } else {
      attentionStartTs.value = null
      drowsyStartTs.value = null
    }

    let finalLevel = 'normal'
    if (drowsyStartTs.value && nowTs - drowsyStartTs.value >= FATIGUE.DROWSY_HOLD_MS) {
      finalLevel = 'drowsy'
    } else if (attentionStartTs.value && nowTs - attentionStartTs.value >= FATIGUE.ATTENTION_HOLD_MS) {
      finalLevel = 'attention'
    }

    if (candidate !== 'normal') {
      highFpsUntil.value = Math.max(highFpsUntil.value, nowTs + FATIGUE.HIGH_FPS_HOLD_MS)
    }

    state.level = finalLevel
    state.visualScore = visualScore
    state.behaviorScore = behaviorScore
    state.fusionScore = fusionScore
    state.headDownRatio = headDownRatio
    state.noFaceRatio = noFaceRatio
    state.confidence = clamp(0.25 + 0.75 * fusionScore, 0, 1)

    // Check level change for alert
    const changed = finalLevel !== lastRiskLevel.value
    lastRiskLevel.value = finalLevel

    // Update sampling rate
    const desiredFps = Date.now() < highFpsUntil.value ? FATIGUE.ALERT_FPS : FATIGUE.NORMAL_FPS
    currentVideoFps.value = desiredFps

    return { changed, level: finalLevel }
  }

  function addVisualSample(facePresent, headDown) {
    visualWindow.value.push({ ts: Date.now(), facePresent, headDown })
  }

  function reset() {
    state.level = 'normal'
    state.confidence = 0
    state.visualScore = 0
    state.behaviorScore = 0
    state.fusionScore = 0
    state.headDownRatio = 0
    state.noFaceRatio = 0
    currentVideoFps.value = FATIGUE.NORMAL_FPS
    highFpsUntil.value = 0
    attentionStartTs.value = null
    drowsyStartTs.value = null
    visualWindow.value = []
  }

  return {
    state, currentVideoFps, highFpsUntil,
    evaluate, addVisualSample, reset,
  }
})
