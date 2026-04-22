import { ref } from 'vue'
import {
  parseLngLat, toAmapLngLat, parsePolylineToPaths,
  getRouteOptions, getOptionPolyline, normalizeJsApiRouteResult,
} from '../utils/map'

export function useAMap() {
  const amapReady = ref(false)

  let amapInstance = null
  let amapMarkers = []
  let amapPolylines = []
  let amapRouteServices = { driving: null, walking: null, riding: null, transit: null }
  let amapRouteDynamicServices = []
  let amapRouteServicesPromise = null
  let amapLoaderPromise = null

  async function initAMap() {
    try {
      const resp = await fetch('/api/amap-key')
      const json = await resp.json()
      const amapKey = json.key
      const amapSecret = json.secret
      const amapServiceHost = json.service_host
      if (!amapKey) { console.warn('[MAP] No AMAP_WEB_KEY'); return }

      if (amapServiceHost) {
        window._AMapSecurityConfig = { serviceHost: amapServiceHost }
      } else {
        window._AMapSecurityConfig = { securityJsCode: amapSecret || '' }
      }

      if (!amapLoaderPromise) {
        amapLoaderPromise = new Promise((resolve, reject) => {
          if (window.AMapLoader?.load) { resolve(window.AMapLoader); return }
          const s = document.createElement('script')
          s.src = 'https://webapi.amap.com/loader.js'
          s.onload = () => window.AMapLoader?.load ? resolve(window.AMapLoader) : reject(new Error('AMapLoader not available'))
          s.onerror = reject
          document.head.appendChild(s)
        })
      }

      const AMapLoader = await amapLoaderPromise
      await AMapLoader.load({
        key: amapKey,
        version: '2.0',
        plugins: ['AMap.Scale', 'AMap.ToolBar', 'AMap.ControlBar', 'AMap.Geolocation', 'AMap.Driving', 'AMap.Walking', 'AMap.Riding', 'AMap.Transfer'],
      })

      amapReady.value = true
      window._amapReady = true
      console.log('[MAP] AMap JS API loaded')
    } catch (e) {
      console.error('[MAP] AMap load failed:', e)
    }
  }

  function ensureMap() {
    if (!amapReady.value || !window.AMap) return null
    const container = document.getElementById('mapContainer')
    if (container) container.style.display = 'block'
    if (!amapInstance) {
      amapInstance = new AMap.Map('mapInner', {
        zoom: 13, center: [114.35, 30.52], resizeEnable: true, viewMode: '3D',
      })
      amapInstance.addControl(new AMap.Scale())
      amapInstance.addControl(new AMap.ToolBar({ position: 'RT' }))
      if (AMap.ControlBar) amapInstance.addControl(new AMap.ControlBar({ position: { right: '10px', top: '70px' } }))
    }
    return amapInstance
  }

  function clearMapOverlays() {
    if (!amapInstance) return
    clearRouteServices()
    amapMarkers.forEach(m => m.setMap(null))
    amapMarkers = []
    amapPolylines.forEach(pl => pl.setMap(null))
    amapPolylines = []
  }

  function clearRouteServices() {
    ['driving', 'walking', 'riding', 'transit'].forEach(mode => {
      const planner = amapRouteServices[mode]
      if (planner?.clear) try { planner.clear() } catch {}
    })
    amapRouteDynamicServices.forEach(p => {
      try { p?.clear?.(); p?.setMap?.(null) } catch {}
    })
    amapRouteDynamicServices = []
  }

  async function ensureRouteServices() {
    const map = ensureMap()
    if (!map || !window.AMap) return false
    if (amapRouteServices.driving && amapRouteServices.walking && amapRouteServices.riding && amapRouteServices.transit) return true

    if (!amapRouteServicesPromise) {
      amapRouteServicesPromise = new Promise((resolve, reject) => {
        try {
          amapRouteServices.driving = new AMap.Driving({ map, hideMarkers: true, showTraffic: true, autoFitView: true, policy: AMap.DrivingPolicy?.LEAST_TIME })
          amapRouteServices.walking = new AMap.Walking({ map, hideMarkers: true, autoFitView: true })
          amapRouteServices.riding = new AMap.Riding({ map, autoFitView: true })
          amapRouteServices.transit = new AMap.Transfer({ map, city: '武汉', policy: AMap.TransferPolicy?.LEAST_TIME })
          resolve(true)
        } catch (err) { reject(err) }
      }).catch(err => { console.warn('[MAP] route services init failed:', err); amapRouteServicesPromise = null; return false })
    }
    return await amapRouteServicesPromise
  }

  function addRouteMarker(position, htmlContent) {
    if (!position || !amapInstance) return
    const marker = new AMap.Marker({ position, content: htmlContent, anchor: 'center', offset: new AMap.Pixel(0, 0), zIndex: 120 })
    amapInstance.add(marker)
    amapMarkers.push(marker)
  }

  function drawPolylinePath(path, options = {}) {
    if (!path?.length || !amapInstance) return
    const pl = new AMap.Polyline({
      path, strokeColor: options.color || '#2563eb', strokeWeight: options.weight || 7,
      strokeOpacity: options.opacity || 0.94, strokeStyle: options.dashed ? 'dashed' : 'solid',
      zIndex: options.zIndex || 95, showDir: options.showDir || false,
    })
    amapInstance.add(pl)
    amapPolylines.push(pl)
  }

  function drawPolylinePaths(paths, options) {
    paths.forEach(path => drawPolylinePath(path, options))
  }

  function styleForSegment(seg, busColorMap, usedBusColorCountRef) {
    const segType = (seg.type || '').toLowerCase()
    const busPalette = ['#2563eb', '#16a34a', '#d97706', '#db2777', '#7c3aed', '#0891b2']
    if (segType === 'walking') return { color: '#64748b', weight: 5, opacity: 0.9, dashed: true, zIndex: 92 }
    if (segType === 'bus') {
      const lineName = seg.line_name || ('bus_' + usedBusColorCountRef.count)
      if (!busColorMap[lineName]) { busColorMap[lineName] = busPalette[usedBusColorCountRef.count % busPalette.length]; usedBusColorCountRef.count++ }
      return { color: busColorMap[lineName], weight: 7, opacity: 0.96, dashed: false, zIndex: 96 }
    }
    return { color: '#2563eb', weight: 7, opacity: 0.94, dashed: false, zIndex: 95, showDir: true }
  }

  function drawActiveRoute(option, route) {
    if (!option) return
    const busColorMap = {}
    const usedBusColorCountRef = { count: 0 }
    if (Array.isArray(option.segments) && option.segments.length > 0) {
      let hasValid = false
      option.segments.forEach(seg => {
        const segPaths = parsePolylineToPaths(seg.polyline || '')
        if (!segPaths.length) return
        hasValid = true
        drawPolylinePaths(segPaths, styleForSegment(seg, busColorMap, usedBusColorCountRef))
      })
      if (hasValid) return
    }
    const polyline = getOptionPolyline(option, route)
    drawPolylinePaths(parsePolylineToPaths(polyline), { color: '#2563eb', weight: 7, opacity: 0.94, showDir: true, zIndex: 95 })
  }

  function drawInactiveRoute(option, route) {
    const polyline = getOptionPolyline(option, route)
    drawPolylinePaths(parsePolylineToPaths(polyline), { color: '#94a3b8', weight: 4, opacity: 0.45, zIndex: 70 })
  }

  async function showRouteOnMap(route, selectedIdx = 0) {
    const map = ensureMap()
    if (!map) return
    clearMapOverlays()

    const routeOptions = getRouteOptions(route)
    if (!routeOptions.length) return
    if (selectedIdx >= routeOptions.length) selectedIdx = 0

    // Add markers
    const originLngLat = parseLngLat(route.origin_location)
    const destLngLat = parseLngLat(route.destination_location)
    if (originLngLat) addRouteMarker(originLngLat, `<div style="background:#0f766e;color:#fff;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:bold;white-space:nowrap;">起 ${route.origin_name || ''}</div>`)
    if (destLngLat) addRouteMarker(destLngLat, `<div style="background:#b45309;color:#fff;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:bold;white-space:nowrap;">终 ${route.destination_name || ''}</div>`)

    const wpLocs = Array.isArray(route.waypoint_locations) ? route.waypoint_locations : []
    const wpNames = Array.isArray(route.waypoints) ? route.waypoints : []
    wpLocs.forEach((loc, idx) => {
      const ll = parseLngLat(loc)
      if (!ll) return
      addRouteMarker(ll, `<div style="background:#7c3aed;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold;white-space:nowrap;">途${idx + 1} ${wpNames[idx] || ''}</div>`)
    })

    // Draw with official nav service
    let serviceDrawn = false
    if (!route._service_already_tried) {
      serviceDrawn = await drawRouteByAmapService(route)
    }
    if (!serviceDrawn) {
      routeOptions.forEach((opt, idx) => { if (idx !== selectedIdx) drawInactiveRoute(opt, route) })
      drawActiveRoute(routeOptions[selectedIdx], route)
      const fitItems = [...amapMarkers, ...amapPolylines]
      if (fitItems.length > 0) map.setFitView(fitItems, false, [70, 70, 70, 70])
    } else {
      map.setFitView(undefined, false, [70, 70, 70, 70])
    }
  }

  async function drawRouteByAmapService(route) {
    const mode = String(route?.route_mode || route?.mode || 'driving').toLowerCase()
    if (!['driving', 'walking', 'bicycling', 'transit'].includes(mode)) return false
    const ready = await ensureRouteServices()
    if (!ready) return false
    const origin = toAmapLngLat(route?.origin_location)
    const destination = toAmapLngLat(route?.destination_location)
    if (!origin || !destination) return false
    clearRouteServices()

    if (mode === 'driving') {
      const wps = (Array.isArray(route.waypoint_locations) ? route.waypoint_locations : []).map(toAmapLngLat).filter(Boolean)
      return new Promise(resolve => {
        try {
          if (wps.length > 0) {
            amapRouteServices.driving.search(origin, destination, { waypoints: wps }, (status) => resolve(status === 'complete'))
          } else {
            amapRouteServices.driving.search(origin, destination, (status) => resolve(status === 'complete'))
          }
        } catch { resolve(false) }
      })
    }

    const checkpoints = buildCheckpoints(route)
    if (mode === 'walking') return drawByOfficialLegs('walking', checkpoints)
    if (mode === 'bicycling') return drawByOfficialLegs('riding', checkpoints)
    if (mode === 'transit') {
      const city = route.city || route.origin_city || '武汉'
      const planner = new AMap.Transfer({ map: ensureMap(), city, policy: AMap.TransferPolicy?.LEAST_TIME })
      amapRouteDynamicServices.push(planner)
      return new Promise(resolve => {
        try { planner.search(origin, destination, (status) => resolve(status === 'complete')) }
        catch { resolve(false) }
      })
    }
    return false
  }

  function buildCheckpoints(route) {
    const points = []
    const o = toAmapLngLat(route?.origin_location)
    if (o) points.push(o)
    ;(Array.isArray(route?.waypoint_locations) ? route.waypoint_locations : []).forEach(loc => { const p = toAmapLngLat(loc); if (p) points.push(p) })
    const d = toAmapLngLat(route?.destination_location)
    if (d) points.push(d)
    return points
  }

  async function drawByOfficialLegs(mode, checkpoints) {
    if (!Array.isArray(checkpoints) || checkpoints.length < 2) return false
    for (let i = 0; i < checkpoints.length - 1; i++) {
      let planner
      const map = ensureMap()
      if (mode === 'walking') planner = new AMap.Walking({ map, hideMarkers: true, autoFitView: false })
      else if (mode === 'riding') planner = new AMap.Riding({ map, autoFitView: false })
      else return false
      amapRouteDynamicServices.push(planner)
      const ok = await new Promise(resolve => {
        try { planner.search(checkpoints[i], checkpoints[i + 1], (status) => resolve(status === 'complete')) }
        catch { resolve(false) }
      })
      if (!ok) return false
    }
    return true
  }

  async function planRouteByJsApi(route) {
    const baseRoute = route || {}
    const mode = String(baseRoute.route_mode || baseRoute.mode || baseRoute.travel_mode || 'driving').toLowerCase()
    const out = { ...baseRoute, _service_already_tried: true }

    if (!['driving', 'walking', 'bicycling'].includes(mode)) {
      return { ...baseRoute, _service_already_tried: false }
    }

    const ready = await ensureRouteServices()
    if (!ready) return out
    const origin = toAmapLngLat(baseRoute.origin_location)
    const destination = toAmapLngLat(baseRoute.destination_location)
    if (!origin || !destination) return out

    const result = await new Promise(resolve => {
      try {
        if (mode === 'driving') {
          const wps = (Array.isArray(baseRoute.waypoint_locations) ? baseRoute.waypoint_locations : []).map(toAmapLngLat).filter(Boolean)
          if (wps.length > 0) amapRouteServices.driving.search(origin, destination, { waypoints: wps }, (s, r) => resolve(s === 'complete' ? r : null))
          else amapRouteServices.driving.search(origin, destination, (s, r) => resolve(s === 'complete' ? r : null))
          return
        }
        if (mode === 'walking') { amapRouteServices.walking.search(origin, destination, (s, r) => resolve(s === 'complete' ? r : null)); return }
        if (mode === 'bicycling') { amapRouteServices.riding.search(origin, destination, (s, r) => resolve(s === 'complete' ? r : null)); return }
        resolve(null)
      } catch { resolve(null) }
    })

    return normalizeJsApiRouteResult(mode, result, baseRoute) || out
  }

  function showCandidatesOnMap(candidates) {
    const map = ensureMap()
    if (!map) return
    clearMapOverlays()
    const colors = { origin: '#0f766e', destination: '#b45309', other: '#2563eb' }
    candidates.forEach((poi, i) => {
      const ll = parseLngLat(poi.location)
      if (!ll) return
      const group = poi.selection_group || 'other'
      const color = colors[group] || '#2563eb'
      const label = group === 'origin' ? '起' : group === 'destination' ? '终' : ''
      const marker = new AMap.Marker({
        position: ll,
        content: `<div style="background:${color};color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold;white-space:nowrap;cursor:pointer;">${label}${i + 1} ${poi.name || ''}</div>`,
        offset: new AMap.Pixel(-40, -12),
      })
      map.add(marker)
      amapMarkers.push(marker)
    })
    if (amapMarkers.length > 0) map.setFitView(amapMarkers, false, [60, 60, 60, 60])
  }

  function destroyMap() {
    if (amapInstance?.destroy) try { amapInstance.destroy() } catch {}
    amapInstance = null
  }

  return {
    amapReady,
    initAMap, ensureMap, clearMapOverlays,
    showRouteOnMap, showCandidatesOnMap, planRouteByJsApi,
    destroyMap,
  }
}
