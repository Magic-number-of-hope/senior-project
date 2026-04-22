import { ref } from 'vue'
import { useSessionStore } from '../stores/session'
import { useMessageStore } from '../stores/messages'
import { useFatigueStore } from '../stores/fatigue'

export function useVideo() {
  const session = useSessionStore()
  const messages = useMessageStore()
  const fatigue = useFatigueStore()

  const isRecordingVideo = ref(false)
  const videoPreviewRef = ref(null)

  let videoStream = null
  let videoFrameInterval = null
  let videoCanvas = null
  let videoCanvasCtx = null
  let faceDetector = null
  let isAnalyzingFrame = false

  function initFaceDetector() {
    if ('FaceDetector' in window) {
      try {
        faceDetector = new FaceDetector({ fastMode: true, maxDetectedFaces: 1 })
      } catch (err) {
        console.warn('FaceDetector init failed:', err)
      }
    }
  }

  async function startVideoRecording(videoEl) {
    if (isRecordingVideo.value) return
    if (!session.isConnected) throw new Error('WebSocket 尚未连接')
    if (!session.sessionCreated) throw new Error('请先创建会话')

    videoStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' },
      audio: false,
    })

    videoEl.srcObject = videoStream
    videoPreviewRef.value = videoEl
    startSendingVideoFrames(videoEl)

    isRecordingVideo.value = true
    messages.addMessage('System', '📹 视频采集已开启：约 1 秒/帧')
  }

  function startSendingVideoFrames(videoEl) {
    if (videoFrameInterval) clearInterval(videoFrameInterval)
    if (!videoCanvas) {
      videoCanvas = document.createElement('canvas')
      videoCanvasCtx = videoCanvas.getContext('2d')
    }

    videoFrameInterval = setInterval(() => {
      if (!isRecordingVideo.value || !videoStream || !videoEl) return
      try {
        if (videoEl.readyState < 2 || !videoEl.videoWidth || !videoEl.videoHeight) return
        if (videoCanvas.width !== videoEl.videoWidth || videoCanvas.height !== videoEl.videoHeight) {
          videoCanvas.width = videoEl.videoWidth
          videoCanvas.height = videoEl.videoHeight
        }
        videoCanvasCtx.drawImage(videoEl, 0, 0, videoEl.videoWidth, videoEl.videoHeight)
        const base64Data = videoCanvas.toDataURL('image/jpeg', 0.8).split(',')[1]

        collectVisualSignals(videoEl)

        if (session.isConnected && session.sessionCreated) {
          session.sendMessage({
            type: 'client_image_append',
            session_id: session.sessionId,
            image: base64Data,
            format: { type: 'image/jpeg', mime_type: 'image/jpeg' },
          })
        }
      } catch (err) {
        console.error('Failed to capture video frame:', err)
      }
    }, Math.round(1000 / fatigue.currentVideoFps))
  }

  async function collectVisualSignals(videoEl) {
    if (!faceDetector || isAnalyzingFrame) return
    if (videoEl.readyState < 2 || !videoEl.videoWidth || !videoEl.videoHeight) return

    isAnalyzingFrame = true
    try {
      const faces = await faceDetector.detect(videoEl)
      if (!faces || faces.length === 0) {
        fatigue.addVisualSample(false, false)
      } else {
        const box = faces[0].boundingBox || { y: 0, height: 0 }
        const centerY = (box.y + box.height * 0.5) / videoEl.videoHeight
        fatigue.addVisualSample(true, centerY > 0.62)
      }
      const result = fatigue.evaluate(Date.now(), session.emaResponseLatencyMs)
      if (result.changed) {
        if (result.level === 'attention') {
          messages.addMessage('System', '⚠️ 疲劳风险提示：检测到注意力下降，请保持专注（AI仅辅助）')
        } else if (result.level === 'drowsy') {
          messages.addMessage('System', '🚨 疲劳风险提示：疑似困倦，请尽快靠边休息（AI仅辅助）')
        } else {
          messages.addMessage('System', '✅ 驾驶状态回到 normal')
        }
      }
    } catch (err) {
      console.warn('Face detection failed:', err)
    } finally {
      isAnalyzingFrame = false
    }
  }

  function stopVideoRecording() {
    if (videoFrameInterval) { clearInterval(videoFrameInterval); videoFrameInterval = null }
    if (videoStream) { videoStream.getTracks().forEach(t => t.stop()); videoStream = null }
    if (videoPreviewRef.value) videoPreviewRef.value.srcObject = null
    isRecordingVideo.value = false
    fatigue.reset()
    messages.addMessage('System', '⏹️ 视频采集已停止')
  }

  initFaceDetector()

  return {
    isRecordingVideo, videoPreviewRef,
    startVideoRecording, stopVideoRecording,
  }
}
