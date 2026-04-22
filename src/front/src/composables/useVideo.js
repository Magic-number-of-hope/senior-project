import { ref, reactive } from 'vue'

const NORMAL_FPS = 1
const ALERT_FPS = 1
const ATTENTION_SCORE = 0.45
const DROWSY_SCORE = 0.72
const ATTENTION_HOLD_MS = 6000
const DROWSY_HOLD_MS = 8000
const HIGH_FPS_HOLD_MS = 15000

function clamp (value, min, max) {
  return Math.max(min, Math.min(max, value))
}

export function useVideo (wsSend, isWsConnected, sessionCreated, sessionId, addMessage) {
  const isRecordingVideo = ref(false)
  const currentVideoFps = ref(NORMAL_FPS)

  const fatigueState = reactive({
    level: 'normal',
    confidence: 0,
    visualScore: 0,
    behaviorScore: 0,
    fusionScore: 0,
    headDownRatio: 0,
    noFaceRatio: 0
  })

  let videoStream = null
  let videoFrameInterval = null
  let videoCanvas = null
  let videoCanvasCtx = null
  let faceDetector = null
  let isAnalyzingFrame = false
  let highFpsUntil = 0
  let attentionStartTs = null
  let drowsyStartTs = null
  let lastRiskLevel = 'normal'
  let visualWindow = []
  let boundVideoPreviewEl = null

  // 响应延迟追踪
  let emaResponseLatencyMs = 0
  let pendingUserInputTs = 0
  let waitingAgentResponse = false

  function initFaceDetector () {
    if ('FaceDetector' in window) {
      try {
        faceDetector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 1 })
      } catch (err) {
        console.warn('FaceDetector init failed:', err)
      }
    }
  }

  function computeBehaviorScore () {
    if (!emaResponseLatencyMs) return 0
    return clamp((emaResponseLatencyMs - 1500) / 3500, 0, 1)
  }

  function evaluateFatigue (nowTs) {
    const recent = visualWindow.filter(item => nowTs - item.ts <= 20000)
    visualWindow = recent

    let headDownRatio = 0
    let noFaceRatio = 0
    if (recent.length > 0) {
      headDownRatio = recent.filter(x => x.headDown).length / recent.length
      noFaceRatio = recent.filter(x => !x.facePresent).length / recent.length
    }

    const visualScore = clamp(0.65 * headDownRatio + 0.35 * noFaceRatio, 0, 1)
    const behaviorScore = computeBehaviorScore()
    const fusionScore = clamp(0.65 * visualScore + 0.35 * behaviorScore, 0, 1)

    let candidate = 'normal'
    if (fusionScore >= DROWSY_SCORE) candidate = 'drowsy'
    else if (fusionScore >= ATTENTION_SCORE) candidate = 'attention'

    if (candidate === 'drowsy') {
      drowsyStartTs = drowsyStartTs || nowTs
      attentionStartTs = attentionStartTs || nowTs
    } else if (candidate === 'attention') {
      attentionStartTs = attentionStartTs || nowTs
      drowsyStartTs = null
    } else {
      attentionStartTs = null
      drowsyStartTs = null
    }

    let finalLevel = 'normal'
    if (drowsyStartTs && nowTs - drowsyStartTs >= DROWSY_HOLD_MS) finalLevel = 'drowsy'
    else if (attentionStartTs && nowTs - attentionStartTs >= ATTENTION_HOLD_MS) finalLevel = 'attention'

    if (candidate !== 'normal') {
      highFpsUntil = Math.max(highFpsUntil, nowTs + HIGH_FPS_HOLD_MS)
    }

    fatigueState.level = finalLevel
    fatigueState.visualScore = visualScore
    fatigueState.behaviorScore = behaviorScore
    fatigueState.fusionScore = fusionScore
    fatigueState.headDownRatio = headDownRatio
    fatigueState.noFaceRatio = noFaceRatio
    fatigueState.confidence = clamp(0.25 + 0.75 * fusionScore, 0, 1)

    maybeSendFatigueAlert(finalLevel)
    updateVideoSamplingRate()
  }

  function maybeSendFatigueAlert (level) {
    if (level === lastRiskLevel) return
    lastRiskLevel = level
    if (level === 'attention') {
      addMessage('System', '⚠️ 疲劳风险提示：检测到注意力下降，请保持专注（AI仅辅助）')
    } else if (level === 'drowsy') {
      addMessage('System', '🚨 疲劳风险提示：疑似困倦，请尽快靠边休息（AI仅辅助）')
    } else {
      addMessage('System', '✅ 驾驶状态回到 normal')
    }
  }

  async function collectVisualSignals (videoPreview) {
    if (!faceDetector || isAnalyzingFrame) return
    if (videoPreview.readyState < 2 || !videoPreview.videoWidth || !videoPreview.videoHeight) return

    isAnalyzingFrame = true
    try {
      const faces = await faceDetector.detect(videoPreview)
      const ts = Date.now()
      if (!faces || faces.length === 0) {
        visualWindow.push({ ts, facePresent: false, headDown: false })
      } else {
        const box = faces[0].boundingBox || { y: 0, height: 0 }
        const centerY = (box.y + box.height * 0.5) / videoPreview.videoHeight
        visualWindow.push({ ts, facePresent: true, headDown: centerY > 0.62 })
      }
      evaluateFatigue(ts)
    } catch (err) {
      console.warn('Face detection failed:', err)
    } finally {
      isAnalyzingFrame = false
    }
  }

  function updateVideoSamplingRate () {
    const desiredFps = (Date.now() < highFpsUntil) ? ALERT_FPS : NORMAL_FPS
    if (desiredFps === currentVideoFps.value) return
    currentVideoFps.value = desiredFps
    if (isRecordingVideo.value && boundVideoPreviewEl) {
      startSendingVideoFrames(boundVideoPreviewEl)
    }
  }

  function onUserInputCommitted () {
    pendingUserInputTs = Date.now()
    waitingAgentResponse = true
  }

  function onAgentResponseStarted () {
    if (!waitingAgentResponse || !pendingUserInputTs) return
    const latency = Date.now() - pendingUserInputTs
    emaResponseLatencyMs = emaResponseLatencyMs
      ? (0.75 * emaResponseLatencyMs + 0.25 * latency)
      : latency
    waitingAgentResponse = false
    pendingUserInputTs = 0
    evaluateFatigue(Date.now())
  }

  function startSendingVideoFrames (videoPreview) {
    if (videoFrameInterval) clearInterval(videoFrameInterval)
    if (!videoCanvas) {
      videoCanvas = document.createElement('canvas')
      videoCanvasCtx = videoCanvas.getContext('2d')
    }

    videoFrameInterval = setInterval(function () {
      if (!isRecordingVideo.value || !videoStream || !videoPreview) return
      try {
        if (videoPreview.readyState < 2 || !videoPreview.videoWidth || !videoPreview.videoHeight) return
        const videoWidth = videoPreview.videoWidth
        const videoHeight = videoPreview.videoHeight
        if (videoCanvas.width !== videoWidth || videoCanvas.height !== videoHeight) {
          videoCanvas.width = videoWidth
          videoCanvas.height = videoHeight
        }
        videoCanvasCtx.drawImage(videoPreview, 0, 0, videoWidth, videoHeight)
        const base64Data = videoCanvas.toDataURL('image/jpeg', 0.8).split(',')[1]

        collectVisualSignals(videoPreview) // fire-and-forget

        if (isWsConnected() && sessionCreated.value) {
          wsSend({
            type: 'client_image_append',
            session_id: sessionId,
            image: base64Data,
            format: { type: 'image/jpeg', mime_type: 'image/jpeg' }
          })
        }
      } catch (err) {
        console.error('Failed to capture video frame:', err)
      }
    }, Math.round(1000 / currentVideoFps.value))
  }

  async function startVideoRecording (videoPreviewEl) {
    if (isRecordingVideo.value) return
    if (!isWsConnected()) throw new Error('WebSocket is not connected!')
    if (!sessionCreated.value) throw new Error('Session not created yet!')

    videoStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' },
      audio: false
    })

    boundVideoPreviewEl = videoPreviewEl
    videoPreviewEl.srcObject = videoStream
    startSendingVideoFrames(videoPreviewEl)

    isRecordingVideo.value = true
    addMessage('System', '📹 视频采集已开启：约 1 秒/帧（后端按变化检测决定是否分析）')
  }

  function stopVideoRecording (videoPreviewEl) {
    if (videoFrameInterval) { clearInterval(videoFrameInterval); videoFrameInterval = null }
    if (videoStream) { videoStream.getTracks().forEach(t => t.stop()); videoStream = null }
    if (videoPreviewEl) { videoPreviewEl.srcObject = null }
    boundVideoPreviewEl = null

    isRecordingVideo.value = false
    visualWindow = []
    attentionStartTs = null
    drowsyStartTs = null
    highFpsUntil = 0
    currentVideoFps.value = NORMAL_FPS
    fatigueState.level = 'normal'
    fatigueState.confidence = 0
    fatigueState.visualScore = 0
    fatigueState.behaviorScore = 0
    fatigueState.fusionScore = 0
    fatigueState.headDownRatio = 0
    fatigueState.noFaceRatio = 0
  }

  function resetFatigue () {
    lastRiskLevel = 'normal'
    emaResponseLatencyMs = 0
  }

  return {
    isRecordingVideo,
    currentVideoFps,
    fatigueState,
    emaResponseLatencyMs: ref(0),
    initFaceDetector,
    startVideoRecording,
    stopVideoRecording,
    onUserInputCommitted,
    onAgentResponseStarted,
    resetFatigue,
    get emaLatency () { return emaResponseLatencyMs }
  }
}
