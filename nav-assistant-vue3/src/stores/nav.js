import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useNavStore = defineStore('nav', () => {
  // Nav status
  const navStatus = ref('idle') // idle | processing | done | error
  const navStatusText = ref('')

  // Intent analysis result
  const intentResult = ref(null)

  // Route result
  const routeResult = ref(null)
  const selectedRouteIndex = ref(0)
  const lastRouteRenderKey = ref('')

  // POI candidates
  const poiCandidates = ref([])
  const poiOriginCandidates = ref([])
  const poiDestinationCandidates = ref([])

  // Missing slots
  const missingSlots = ref([])
  const currentSlots = ref({})

  // Actions
  function updateNavStatus(state, text) {
    navStatus.value = state
    navStatusText.value = text || ''
    if (state === 'done' || state === 'error') {
      setTimeout(() => { navStatus.value = 'idle' }, state === 'done' ? 2000 : 4000)
    }
  }

  function setIntentResult(result) {
    intentResult.value = result
  }

  function setRouteResult(route) {
    routeResult.value = route
  }

  function setSelectedRouteIndex(idx) {
    selectedRouteIndex.value = idx
  }

  function setPOICandidates(candidates, origin, destination) {
    let final = Array.isArray(candidates) ? [...candidates] : []
    if (final.length === 0) {
      const o = Array.isArray(origin) ? origin : []
      const d = Array.isArray(destination) ? destination : []
      o.forEach(item => final.push({ ...item, selection_group: 'origin' }))
      d.forEach(item => final.push({ ...item, selection_group: 'destination' }))
    }
    poiCandidates.value = final
    poiOriginCandidates.value = origin || []
    poiDestinationCandidates.value = destination || []
  }

  function clearPOICandidates() {
    poiCandidates.value = []
    poiOriginCandidates.value = []
    poiDestinationCandidates.value = []
  }

  function setMissingSlots(missing, slots) {
    missingSlots.value = missing || []
    currentSlots.value = slots || {}
  }

  function clearMissingSlots() {
    missingSlots.value = []
    currentSlots.value = {}
  }

  return {
    navStatus, navStatusText,
    intentResult, routeResult, selectedRouteIndex, lastRouteRenderKey,
    poiCandidates, poiOriginCandidates, poiDestinationCandidates,
    missingSlots, currentSlots,
    updateNavStatus, setIntentResult, setRouteResult, setSelectedRouteIndex,
    setPOICandidates, clearPOICandidates, setMissingSlots, clearMissingSlots,
  }
})
