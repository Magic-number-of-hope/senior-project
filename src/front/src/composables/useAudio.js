import { ref } from 'vue'

export function useAudio (wsSend, isWsConnected) {
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

  function convertToPCM16 (float32Array) {
    const int16Array = new Int16Array(float32Array.length)
    for (let i = 0; i < float32Array.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Array[i]))
      int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
    }
    return int16Array.buffer
  }

  function arrayBufferToBase64 (buffer) {
    const bytes = new Uint8Array(buffer)
    let binary = ''
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i])
    }
    return btoa(binary)
  }

  async function startRecording (sessionId) {
    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000
      })
    }
    if (audioContext.state === 'suspended') {
      await audioContext.resume()
    }

    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 16000 }
    })

    if (recordProcessorNode) { try { recordProcessorNode.disconnect() } catch (e) {} recordProcessorNode = null }
    if (recordSourceNode) { try { recordSourceNode.disconnect() } catch (e) {} recordSourceNode = null }
    if (recordDummyGainNode) { try { recordDummyGainNode.disconnect() } catch (e) {} recordDummyGainNode = null }

    recordSourceNode = audioContext.createMediaStreamSource(mediaStream)
    recordProcessorNode = audioContext.createScriptProcessor(4096, 1, 1)

    let audioChunkCount = 0
    recordProcessorNode.onaudioprocess = function (e) {
      if (!isRecording.value) return
      const inputData = e.inputBuffer.getChannelData(0)
      const pcmData = convertToPCM16(inputData)
      const base64Audio = arrayBufferToBase64(pcmData)

      if (isWsConnected()) {
        audioChunkCount++
        if (audioChunkCount % 10 === 0) {
          console.log(`Sending audio chunk ${audioChunkCount}`)
        }
        wsSend({
          type: 'client_audio_append',
          session_id: sessionId,
          audio: base64Audio,
          format: { rate: 16000, type: 'audio/pcm' }
        })
      }
    }

    recordSourceNode.connect(recordProcessorNode)
    recordDummyGainNode = audioContext.createGain()
    recordDummyGainNode.gain.value = 0
    recordProcessorNode.connect(recordDummyGainNode)
    recordDummyGainNode.connect(audioContext.destination)

    isRecording.value = true
  }

  function stopRecording (sessionId) {
    isRecording.value = false

    if (recordProcessorNode) {
      try { recordProcessorNode.onaudioprocess = null; recordProcessorNode.disconnect() } catch (e) {}
      recordProcessorNode = null
    }
    if (recordSourceNode) { try { recordSourceNode.disconnect() } catch (e) {} recordSourceNode = null }
    if (recordDummyGainNode) { try { recordDummyGainNode.disconnect() } catch (e) {} recordDummyGainNode = null }

    if (mediaStream) {
      mediaStream.getTracks().forEach(track => track.stop())
      mediaStream = null
    }

    if (isWsConnected()) {
      wsSend({ type: 'client_audio_commit', session_id: sessionId })
    }
  }

  function queueAudioChunk (base64Audio) {
    try {
      const binaryString = atob(base64Audio)
      const bytes = new Uint8Array(binaryString.length)
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i)
      }
      const int16Array = new Int16Array(bytes.buffer)
      const float32Array = new Float32Array(int16Array.length)
      for (let i = 0; i < int16Array.length; i++) {
        float32Array[i] = int16Array[i] / 32768.0
      }
      audioPlaybackQueue.push(float32Array)

      if (!isPlaying.value) {
        startAudioPlayback()
      }
    } catch (err) {
      console.error('Failed to decode audio chunk:', err)
    }
  }

  function startAudioPlayback () {
    if (isPlaying.value) return
    try {
      if (!playbackAudioContext) {
        playbackAudioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 })
      }
      if (playbackAudioContext.state === 'suspended') {
        playbackAudioContext.resume()
      }
      isPlaying.value = true
      audioPlaybackIndex = 0

      const bufferSize = 4096
      const processor = playbackAudioContext.createScriptProcessor(bufferSize, 0, 1)

      processor.onaudioprocess = function (e) {
        const output = e.outputBuffer.getChannelData(0)
        const samplesNeeded = output.length
        let samplesWritten = 0

        while (samplesWritten < samplesNeeded && audioPlaybackQueue.length > 0) {
          const chunk = audioPlaybackQueue[0]
          const samplesToRead = Math.min(samplesNeeded - samplesWritten, chunk.length - audioPlaybackIndex)
          for (let i = 0; i < samplesToRead; i++) {
            output[samplesWritten + i] = chunk[audioPlaybackIndex + i]
          }
          samplesWritten += samplesToRead
          audioPlaybackIndex += samplesToRead
          if (audioPlaybackIndex >= chunk.length) {
            audioPlaybackQueue.shift()
            audioPlaybackIndex = 0
          }
        }

        if (samplesWritten < samplesNeeded) {
          for (let i = samplesWritten; i < samplesNeeded; i++) {
            output[i] = 0
          }
          if (audioPlaybackQueue.length === 0) {
            setTimeout(() => {
              if (audioPlaybackQueue.length === 0) {
                stopAudioPlayback()
              }
            }, 100)
          }
        }
      }

      processor.connect(playbackAudioContext.destination)
      audioPlaybackNode = processor
    } catch (err) {
      console.error('Failed to start audio playback:', err)
      isPlaying.value = false
    }
  }

  function stopAudioPlayback () {
    if (audioPlaybackNode) {
      audioPlaybackNode.disconnect()
      audioPlaybackNode = null
    }
    isPlaying.value = false
    audioPlaybackQueue = []
    audioPlaybackIndex = 0
  }

  return {
    isRecording,
    isPlaying,
    startRecording,
    stopRecording,
    queueAudioChunk,
    stopAudioPlayback
  }
}
