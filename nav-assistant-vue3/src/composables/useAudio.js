import { ref } from 'vue'
import { useSessionStore } from '../stores/session'
import { useMessageStore } from '../stores/messages'
import { convertToPCM16, arrayBufferToBase64, decodeBase64Audio } from '../utils/audio'

export function useAudio() {
  const session = useSessionStore()
  const messages = useMessageStore()

  const isRecording = ref(false)
  const isPlaying = ref(false)

  let audioContext = null
  let playbackAudioContext = null
  let mediaStream = null
  let recordSourceNode = null
  let recordProcessorNode = null
  let recordDummyGainNode = null
  let audioPlaybackNode = null
  let audioPlaybackQueue = []
  let audioPlaybackIndex = 0

  async function startRecording() {
    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 })
    }
    if (audioContext.state === 'suspended') await audioContext.resume()

    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 16000 },
    })

    cleanup()

    recordSourceNode = audioContext.createMediaStreamSource(mediaStream)
    recordProcessorNode = audioContext.createScriptProcessor(4096, 1, 1)

    recordProcessorNode.onaudioprocess = (e) => {
      if (!isRecording.value || !session.isConnected) return
      const inputData = e.inputBuffer.getChannelData(0)
      const pcmBuffer = convertToPCM16(inputData)
      const base64Audio = arrayBufferToBase64(pcmBuffer)
      session.sendMessage({
        type: 'client_audio_append',
        session_id: session.sessionId,
        audio: base64Audio,
        format: { rate: 16000, type: 'audio/pcm' },
      })
    }

    recordSourceNode.connect(recordProcessorNode)
    recordDummyGainNode = audioContext.createGain()
    recordDummyGainNode.gain.value = 0
    recordProcessorNode.connect(recordDummyGainNode)
    recordDummyGainNode.connect(audioContext.destination)

    isRecording.value = true
    messages.addMessage('System', '🎤 语音对话已开始...')
  }

  function stopRecording() {
    isRecording.value = false
    cleanup()

    if (mediaStream) {
      mediaStream.getTracks().forEach(t => t.stop())
      mediaStream = null
    }

    if (session.isConnected) {
      session.sendMessage({ type: 'client_audio_commit', session_id: session.sessionId })
    }
    messages.addMessage('System', '⏹️ 语音对话已停止')
  }

  function cleanup() {
    if (recordProcessorNode) {
      try { recordProcessorNode.onaudioprocess = null; recordProcessorNode.disconnect() } catch {}
      recordProcessorNode = null
    }
    if (recordSourceNode) {
      try { recordSourceNode.disconnect() } catch {}
      recordSourceNode = null
    }
    if (recordDummyGainNode) {
      try { recordDummyGainNode.disconnect() } catch {}
      recordDummyGainNode = null
    }
  }

  function queueAudioChunk(base64Audio) {
    try {
      const float32Array = decodeBase64Audio(base64Audio)
      audioPlaybackQueue.push(float32Array)
      if (!isPlaying.value) startPlayback()
    } catch (err) {
      console.error('Failed to decode audio chunk:', err)
    }
  }

  function startPlayback() {
    if (isPlaying.value) return
    try {
      if (!playbackAudioContext) {
        playbackAudioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 })
      }
      if (playbackAudioContext.state === 'suspended') playbackAudioContext.resume()

      isPlaying.value = true
      audioPlaybackIndex = 0

      const processor = playbackAudioContext.createScriptProcessor(4096, 0, 1)
      processor.onaudioprocess = (e) => {
        const output = e.outputBuffer.getChannelData(0)
        let written = 0
        while (written < output.length && audioPlaybackQueue.length > 0) {
          const chunk = audioPlaybackQueue[0]
          const toRead = Math.min(output.length - written, chunk.length - audioPlaybackIndex)
          for (let i = 0; i < toRead; i++) output[written + i] = chunk[audioPlaybackIndex + i]
          written += toRead
          audioPlaybackIndex += toRead
          if (audioPlaybackIndex >= chunk.length) {
            audioPlaybackQueue.shift()
            audioPlaybackIndex = 0
          }
        }
        for (let i = written; i < output.length; i++) output[i] = 0
        if (written < output.length && audioPlaybackQueue.length === 0) {
          setTimeout(() => { if (audioPlaybackQueue.length === 0) stopPlayback() }, 100)
        }
      }
      processor.connect(playbackAudioContext.destination)
      audioPlaybackNode = processor
    } catch (err) {
      console.error('Failed to start audio playback:', err)
      isPlaying.value = false
    }
  }

  function stopPlayback() {
    if (audioPlaybackNode) { audioPlaybackNode.disconnect(); audioPlaybackNode = null }
    isPlaying.value = false
    audioPlaybackQueue = []
    audioPlaybackIndex = 0
  }

  // Register global callback for WS audio events
  window.__audioPlaybackCallback = queueAudioChunk

  return {
    isRecording, isPlaying,
    startRecording, stopRecording, stopPlayback,
  }
}
