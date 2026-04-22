import { ref } from 'vue'

/* global AMap */

const MODE_LABELS = {
  driving: '驾车',
  walking: '步行',
  transit: '公交',
  bicycling: '骑行'
}

function normalizeRouteMode (mode) {
  const rawValue = mode && typeof mode === 'object' && 'value' in mode ? mode.value : mode
  let raw = String(rawValue || '').trim().toLowerCase()
  if (raw.startsWith('travelmode.')) raw = raw.split('.').pop()
  if (raw === 'riding' || raw === 'bike' || raw === 'bicycle') return 'bicycling'
  return raw
}

export function useAmap (wsSend, isWsConnected) {
  /* ── 状态 ── */
  let amapInstance = null
  const amapReady = ref(false)
  const mapStatus = ref('idle')
  const mapStatusMessage = ref('等待地图初始化')
  let amapMarkers = []
  let amapPolylines = []
  const selectedRouteIndex = ref(0)
  const latestRoutePayload = ref(null)
  const amapRouteServices = { driving: null, walking: null, riding: null, transit: null }
  let amapRouteDynamicServices = []
  let amapRouteServicesPromise = null
  let amapLoaderPromise = null

  /* ── initAMap ── */
  async function initAMap () {
    mapStatus.value = 'loading'
    mapStatusMessage.value = '正在加载地图服务...'
    try {
      const resp = await fetch('/api/amap-key')
      const json = await resp.json()
      const amapKey = json.key
      const amapSecret = json.secret
      const amapServiceHost = json.service_host
      if (!amapKey) {
        console.warn('[MAP] No AMAP_WEB_KEY, map disabled')
        mapStatus.value = 'unavailable'
        mapStatusMessage.value = '地图不可用：当前运行环境缺少高德 Web Key'
        return
      }

      if (amapServiceHost) {
        window._AMapSecurityConfig = { serviceHost: amapServiceHost }
      } else {
        window._AMapSecurityConfig = { securityJsCode: amapSecret || '' }
      }

      if (!amapLoaderPromise) {
        amapLoaderPromise = new Promise(function (resolve, reject) {
          if (window.AMapLoader && typeof window.AMapLoader.load === 'function') {
            resolve(window.AMapLoader)
            return
          }
          const s = document.createElement('script')
          s.src = 'https://webapi.amap.com/loader.js'
          s.onload = function () {
            if (window.AMapLoader && typeof window.AMapLoader.load === 'function') {
              resolve(window.AMapLoader)
              return
            }
            reject(new Error('AMapLoader not available'))
          }
          s.onerror = reject
          document.head.appendChild(s)
        })
      }

      const AMapLoader = await amapLoaderPromise
      await AMapLoader.load({
        key: amapKey,
        version: '2.0',
        plugins: [
          'AMap.Scale',
          'AMap.ToolBar',
          'AMap.ControlBar',
          'AMap.Geolocation',
          'AMap.Driving',
          'AMap.Walking',
          'AMap.Riding',
          'AMap.Transfer'
        ]
      })

      amapReady.value = true
      mapStatus.value = 'ready'
      mapStatusMessage.value = '地图已就绪，等待路线或候选点绘制'
      console.log('[MAP] AMap JS API loaded')
    } catch (e) {
      console.error('[MAP] AMap load failed:', e)
      mapStatus.value = 'error'
      mapStatusMessage.value = '地图加载失败：' + (e && e.message ? e.message : '请检查高德配置')
    }
  }

  /* ── DOM 容器引用（由外部注册） ── */
  let _containerEl = null
  let _innerEl = null
  function setMapContainer (containerEl, innerEl) {
    _containerEl = containerEl
    _innerEl = innerEl
  }

  /* ── ensureMap ── */
  function ensureMap (containerEl, innerEl) {
    if (!amapReady.value || !window.AMap) return null
    const cEl = containerEl || _containerEl
    const iEl = innerEl || _innerEl
    if (cEl) cEl.style.display = 'block'
    if (!amapInstance && iEl) {
      amapInstance = new AMap.Map(iEl, {
        zoom: 13,
        center: [114.35, 30.52],
        resizeEnable: true,
        viewMode: '3D'
      })
      amapInstance.on('complete', function () {
        console.log('[MAP] map complete')
      })
      amapInstance.addControl(new AMap.Scale())
      amapInstance.addControl(new AMap.ToolBar({ position: 'RT' }))
      if (AMap.ControlBar) {
        amapInstance.addControl(new AMap.ControlBar({
          position: { right: '10px', top: '70px' }
        }))
      }
    }
    return amapInstance
  }

  // 提供一个 getter 让外部拿到 amapReady
  function isAmapReady () {
    return amapReady.value
  }

  // 提供 getter 让 useLocation 获得 amapReady + AMap.Geolocation
  function getAmapReadyState () {
    return amapReady.value && !!window.AMap
  }

  /* ── clearRouteServices ── */
  function clearRouteServices () {
    ['driving', 'walking', 'riding', 'transit'].forEach(function (mode) {
      const planner = amapRouteServices[mode]
      if (planner && typeof planner.clear === 'function') {
        try { planner.clear() } catch (e) {
          console.warn('[MAP] clear route service failed:', mode, e)
        }
      }
    })

    amapRouteDynamicServices.forEach(function (planner) {
      if (!planner) return
      try {
        if (typeof planner.clear === 'function') planner.clear()
        if (typeof planner.setMap === 'function') planner.setMap(null)
      } catch (e) {
        console.warn('[MAP] clear dynamic route service failed:', e)
      }
    })
    amapRouteDynamicServices = []
  }

  /* ── clearMapOverlays ── */
  function clearMapOverlays () {
    if (!amapInstance) return
    clearRouteServices()
    amapMarkers.forEach(function (m) { m.setMap(null) })
    amapMarkers = []
    amapPolylines.forEach(function (pl) { pl.setMap(null) })
    amapPolylines = []
  }

  /* ── ensureRouteServices ── */
  async function ensureRouteServices () {
    const map = ensureMap()
    if (!map || !window.AMap) return false

    if (amapRouteServices.driving && amapRouteServices.walking &&
        amapRouteServices.riding && amapRouteServices.transit) {
      return true
    }

    if (!amapRouteServicesPromise) {
      amapRouteServicesPromise = new Promise(function (resolve, reject) {
        try {
          amapRouteServices.driving = new AMap.Driving({
            map: map,
            hideMarkers: true,
            showTraffic: true,
            autoFitView: true,
            policy: (window.AMap && AMap.DrivingPolicy)
              ? AMap.DrivingPolicy.LEAST_TIME
              : undefined
          })
          amapRouteServices.walking = new AMap.Walking({
            map: map,
            hideMarkers: true,
            autoFitView: true
          })
          amapRouteServices.riding = new AMap.Riding({
            map: map,
            autoFitView: true
          })
          amapRouteServices.transit = new AMap.Transfer({
            map: map,
            city: '武汉',
            policy: (window.AMap && AMap.TransferPolicy)
              ? AMap.TransferPolicy.LEAST_TIME
              : undefined
          })
          resolve(true)
        } catch (err) {
          reject(err)
        }
      }).catch(function (err) {
        console.warn('[MAP] route services init failed:', err)
        amapRouteServicesPromise = null
        return false
      })
    }

    return await amapRouteServicesPromise
  }

  /* ── 坐标解析工具 ── */
  function parseLngLat (locStr) {
    if (!locStr) return null
    if (Array.isArray(locStr) && locStr.length >= 2) {
      const aLng = parseFloat(locStr[0])
      const aLat = parseFloat(locStr[1])
      if (!isNaN(aLng) && !isNaN(aLat)) return [aLng, aLat]
    }
    if (typeof locStr === 'object' && locStr.lng != null && locStr.lat != null) {
      const oLng = parseFloat(locStr.lng)
      const oLat = parseFloat(locStr.lat)
      if (!isNaN(oLng) && !isNaN(oLat)) return [oLng, oLat]
    }
    if (typeof locStr !== 'string') return null
    const parts = locStr.split(',')
    if (parts.length < 2) return null
    const lng = parseFloat(parts[0])
    const lat = parseFloat(parts[1])
    if (isNaN(lng) || isNaN(lat)) return null
    return [lng, lat]
  }

  function toAmapLngLat (point) {
    const p = parseLngLat(point)
    if (!p) return null
    return new AMap.LngLat(p[0], p[1])
  }

  function lngLatObjToPairString (point) {
    if (!point) return ''
    const lng = typeof point.getLng === 'function' ? point.getLng() : point.lng
    const lat = typeof point.getLat === 'function' ? point.getLat() : point.lat
    if (lng == null || lat == null) return ''
    return Number(lng).toFixed(6) + ',' + Number(lat).toFixed(6)
  }

  function lngLatToArray (point) {
    if (!point) return null
    if (Array.isArray(point) && point.length >= 2) {
      return [Number(point[0]), Number(point[1])]
    }
    if (typeof point === 'object') {
      const lng = typeof point.getLng === 'function' ? point.getLng() : point.lng
      const lat = typeof point.getLat === 'function' ? point.getLat() : point.lat
      if (lng != null && lat != null) return [Number(lng), Number(lat)]
    }
    return null
  }

  function squaredDistance (a, b) {
    const aa = lngLatToArray(a)
    const bb = lngLatToArray(b)
    if (!aa || !bb) return Number.POSITIVE_INFINITY
    const dx = aa[0] - bb[0]
    const dy = aa[1] - bb[1]
    return dx * dx + dy * dy
  }

  function findNearestPathIndex (points, target, startIndex) {
    if (!Array.isArray(points) || points.length === 0) return -1
    const from = Math.max(0, Number(startIndex) || 0)
    let bestIdx = -1
    let bestDist = Number.POSITIVE_INFINITY
    for (let i = from; i < points.length; i++) {
      const d = squaredDistance(points[i], target)
      if (d < bestDist) {
        bestDist = d
        bestIdx = i
      }
    }
    return bestIdx
  }

  function parsePolylineToPaths (polylineStr) {
    if (!polylineStr || typeof polylineStr !== 'string') return []
    const segments = polylineStr.split('|')
    const paths = []
    segments.forEach(function (segStr) {
      const seg = (segStr || '').trim()
      if (!seg) return
      const points = seg.split(';')
      const path = []
      points.forEach(function (pointStr) {
        const p = parseLngLat(pointStr.trim())
        if (p) path.push(new AMap.LngLat(p[0], p[1]))
      })
      if (path.length >= 2) paths.push(path)
    })
    return paths
  }

  /* ── stepToPolyline ── */
  function stepToPolyline (step) {
    if (!step) return ''
    if (Array.isArray(step.path) && step.path.length > 0) {
      const pointPairs = step.path
        .map(lngLatObjToPairString)
        .filter(function (s) { return !!s })
      return pointPairs.join(';')
    }
    if (typeof step.polyline === 'string' && step.polyline) return step.polyline
    return ''
  }

  function pathToPolyline (path) {
    if (!Array.isArray(path) || path.length === 0) return ''
    return path
      .map(lngLatObjToPairString)
      .filter(function (s) { return !!s })
      .join(';')
  }

  function normalizeTransitPlans (result, baseRoute) {
    const plansRaw = Array.isArray(result && result.plans) ? result.plans : []
    if (!plansRaw.length) return null

    const options = plansRaw.map(function (plan, idx) {
      const segments = []
      const steps = []
      let transitLegCount = 0

      const planSegments = Array.isArray(plan && plan.segments) ? plan.segments : []
      planSegments.forEach(function (segment) {
        if (!segment || !segment.transit) return

        const transitMode = String(segment.transit_mode || '').toUpperCase()
        if (transitMode === 'WALK') {
          const walkSteps = Array.isArray(segment.transit.steps) ? segment.transit.steps : []
          const walkPolyline = walkSteps
            .map(stepToPolyline)
            .filter(function (polyline) { return !!polyline })
            .join('|')

          if (walkPolyline) {
            segments.push({
              type: 'walking',
              line_name: '步行',
              polyline: walkPolyline
            })
          }

          if (walkSteps.length > 0) {
            walkSteps.forEach(function (step) {
              steps.push({
                instruction: step.instruction || segment.instruction || '步行',
                distance: String(step.distance != null ? step.distance : '')
              })
            })
          } else if (segment.instruction) {
            steps.push({
              instruction: segment.instruction,
              distance: String(segment.distance != null ? segment.distance : '')
            })
          }
          return
        }

        transitLegCount += 1
        const lineNames = Array.isArray(segment.transit.lines)
          ? segment.transit.lines
            .map(function (line) { return line && line.name ? line.name : '' })
            .filter(function (name) { return !!name })
          : []
        const lineName = lineNames.join(' / ') || segment.instruction || transitMode || '公交'
        const transitPolyline = pathToPolyline(segment.transit.path)

        if (transitPolyline) {
          segments.push({
            type: 'bus',
            line_name: lineName,
            polyline: transitPolyline
          })
        }

        steps.push({
          instruction: segment.instruction || lineName,
          distance: String(segment.distance != null ? segment.distance : '')
        })
      })

      const routePolyline = segments
        .map(function (segment) { return segment.polyline || '' })
        .filter(function (polyline) { return !!polyline })
        .join('|')

      return {
        route_index: idx,
        summary: '公交方案' + (idx + 1),
        distance: String(plan && plan.distance != null ? plan.distance : ''),
        duration: String(plan && plan.time != null ? plan.time : ''),
        taxi_cost: String(plan && plan.cost != null ? plan.cost : (result && result.taxi_cost != null ? result.taxi_cost : (baseRoute && baseRoute.taxi_cost) || '')),
        transfer_count: Math.max(transitLegCount - 1, 0),
        steps: steps,
        polyline: routePolyline,
        segments: segments
      }
    })

    if (!options.length) return null
    const best = options[0]
    const hasDrawable = Boolean(best.polyline) ||
      (Array.isArray(best.segments) && best.segments.length > 0)

    return Object.assign({}, baseRoute || {}, {
      status: 'success',
      mode: 'transit',
      route_mode: 'transit',
      route_count: options.length,
      routes: options,
      distance: best.distance,
      duration: best.duration,
      taxi_cost: best.taxi_cost,
      transfer_count: best.transfer_count,
      steps: best.steps,
      polyline: best.polyline,
      segments: best.segments,
      _skip_service_search: hasDrawable,
      _service_already_tried: hasDrawable
    })
  }

  /* ── normalizeJsApiRouteResult ── */
  function normalizeJsApiRouteResult (mode, result, baseRoute) {
    if (mode === 'transit') {
      return normalizeTransitPlans(result, baseRoute)
    }

    const routesRaw = Array.isArray(result && result.routes) ? result.routes : []
    if (!routesRaw.length) return null

    const routeMode = mode === 'bicycling' ? 'bicycling' : mode
    const options = routesRaw.map(function (r, idx) {
      // 骑行结果常见为 rides[]，其余模式通常是 steps[]。
      const stepsRaw = Array.isArray(r.steps) && r.steps.length > 0
        ? r.steps
        : (Array.isArray(r.rides) ? r.rides : [])
      const stepList = stepsRaw.map(function (s) {
        return {
          instruction: s.instruction || s.action || '',
          distance: String(s.distance != null ? s.distance : '')
        }
      })

      const polylineSegments = stepsRaw
        .map(stepToPolyline)
        .filter(function (s) { return !!s })
      const routePolyline = polylineSegments.join('|')

      const duration = r.time != null ? r.time : r.duration
      return {
        route_index: idx,
        summary: routeMode + '方案' + (idx + 1),
        distance: String(r.distance != null ? r.distance : ''),
        duration: String(duration != null ? duration : ''),
        taxi_cost: String(result && result.taxi_cost != null ? result.taxi_cost : (baseRoute && baseRoute.taxi_cost) || ''),
        steps: stepList,
        polyline: routePolyline,
        segments: routePolyline
          ? [{
              type: routeMode,
              line_name: routeMode,
              polyline: routePolyline
            }]
          : []
      }
    })

    if (!options.length) return null
    const best = options[0]
    const hasDrawable = Boolean(best.polyline) ||
      (Array.isArray(best.segments) && best.segments.length > 0)

    return Object.assign({}, baseRoute || {}, {
      status: 'success',
      mode: routeMode,
      route_mode: routeMode,
      route_count: options.length,
      routes: options,
      distance: best.distance,
      duration: best.duration,
      taxi_cost: best.taxi_cost,
      steps: best.steps,
      polyline: best.polyline,
      segments: best.segments,
      _skip_service_search: hasDrawable,
      _service_already_tried: hasDrawable
    })
  }

  /* ── planRouteByJsApiOnce ── */
  async function planRouteByJsApiOnce (route) {
    const baseRoute = route || {}
    const mode = normalizeRouteMode(baseRoute.route_mode || baseRoute.mode || baseRoute.travel_mode || 'driving')

    const out = Object.assign({}, baseRoute, {
      // JS API 规划失败时，允许 showRouteOnMap 回退到官方服务绘制。
      _service_already_tried: false
    })

    if (!['driving', 'walking', 'bicycling', 'transit'].includes(mode)) {
      return Object.assign({}, baseRoute, {
        _service_already_tried: false
      })
    }

    const ready = await ensureRouteServices()
    if (!ready) return out

    const origin = toAmapLngLat(baseRoute.origin_location)
    const destination = toAmapLngLat(baseRoute.destination_location)
    if (!origin || !destination) return out

    const result = await new Promise(function (resolve) {
      try {
        if (mode === 'driving') {
          const wps = (Array.isArray(baseRoute.waypoint_locations) ? baseRoute.waypoint_locations.slice(0, 16) : [])
            .map(function (loc) { return toAmapLngLat(loc) })
            .filter(function (p) { return !!p })
          if (wps.length > 0) {
            amapRouteServices.driving.search(origin, destination, { waypoints: wps }, function (status, r) {
              resolve(status === 'complete' ? r : null)
            })
          } else {
            amapRouteServices.driving.search(origin, destination, function (status, r) {
              resolve(status === 'complete' ? r : null)
            })
          }
          return
        }

        if (mode === 'walking') {
          amapRouteServices.walking.search(origin, destination, function (status, r) {
            resolve(status === 'complete' ? r : null)
          })
          return
        }

        if (mode === 'bicycling') {
          amapRouteServices.riding.search(origin, destination, function (status, r) {
            resolve(status === 'complete' ? r : null)
          })
          return
        }

        if (mode === 'transit') {
          amapRouteServices.transit.search(origin, destination, function (status, r) {
            resolve(status === 'complete' ? r : null)
          })
          return
        }

        resolve(null)
      } catch (err) {
        console.warn('[MAP] JS API route planning failed:', err)
        resolve(null)
      }
    })

    const normalized = normalizeJsApiRouteResult(mode, result, baseRoute)
    return normalized || out
  }

  /* ── doDrivingSearchWithWaypoints ── */
  function doDrivingSearchWithWaypoints (driving, origin, destination, waypointPoints) {
    return new Promise(function (resolve) {
      const wps = Array.isArray(waypointPoints) ? waypointPoints.slice(0, 16) : []

      try {
        if (wps.length > 0) {
          driving.search(origin, destination, { waypoints: wps }, function (status) {
            resolve(status === 'complete')
          })
        } else {
          driving.search(origin, destination, function (status) {
            resolve(status === 'complete')
          })
        }
        return
      } catch (e) { /* fallback */ }

      const points = [origin].concat(wps).concat([destination])
      try {
        driving.search(points, function (status) {
          resolve(status === 'complete')
        })
        return
      } catch (e2) { /* ignore */ }

      try {
        driving.search(origin, destination, function (status) {
          resolve(status === 'complete')
        })
      } catch (err) {
        console.warn('[MAP] driving.search failed:', err)
        resolve(false)
      }
    })
  }

  /* ── buildSearchCheckpoints ── */
  function buildSearchCheckpoints (route) {
    const points = []
    const origin = toAmapLngLat(route && route.origin_location)
    if (origin) points.push(origin)

    const waypointLocs = Array.isArray(route && route.waypoint_locations)
      ? route.waypoint_locations
      : []
    waypointLocs.forEach(function (loc) {
      const wp = toAmapLngLat(loc)
      if (wp) points.push(wp)
    })

    const destination = toAmapLngLat(route && route.destination_location)
    if (destination) points.push(destination)
    return points
  }

  /* ── inferTransitCity ── */
  function inferTransitCity (route) {
    const candidates = [
      route && route.city,
      route && route.cityname,
      route && route.city1,
      route && route.origin_city,
      route && route.destination_city
    ]
    for (let i = 0; i < candidates.length; i++) {
      const c = (candidates[i] || '').trim()
      if (c) return c
    }
    return '武汉'
  }

  /* ── createRoutePlanner ── */
  function createRoutePlanner (mode, city) {
    const map = ensureMap()
    if (!map || !window.AMap) return null

    if (mode === 'walking') {
      return new AMap.Walking({ map: map, hideMarkers: true, autoFitView: false })
    }
    if (mode === 'riding') {
      return new AMap.Riding({ map: map, autoFitView: false })
    }
    if (mode === 'transit') {
      return new AMap.Transfer({
        map: map,
        city: city || '武汉',
        policy: (window.AMap && AMap.TransferPolicy) ? AMap.TransferPolicy.LEAST_TIME : undefined
      })
    }
    return null
  }

  /* ── runPlannerSearch ── */
  function runPlannerSearch (planner, mode, fromPoint, toPoint) {
    return new Promise(function (resolve) {
      try {
        planner.search(fromPoint, toPoint, function (status) {
          resolve(status === 'complete')
        })
      } catch (err) {
        console.warn('[MAP] ' + mode + '.search failed:', err)
        resolve(false)
      }
    })
  }

  /* ── drawByOfficialLegs ── */
  async function drawByOfficialLegs (mode, checkpoints, city) {
    if (!Array.isArray(checkpoints) || checkpoints.length < 2) return false

    let allSuccess = true
    for (let i = 0; i < checkpoints.length - 1; i++) {
      const planner = createRoutePlanner(mode, city)
      if (!planner) return false
      amapRouteDynamicServices.push(planner)

      const ok = await runPlannerSearch(planner, mode, checkpoints[i], checkpoints[i + 1])
      if (!ok) {
        allSuccess = false
        break
      }
    }
    return allSuccess
  }

  /* ── drawRouteByAmapNavigationService ── */
  async function drawRouteByAmapNavigationService (route) {
    const mode = String((route && (route.route_mode || route.mode)) || 'driving').toLowerCase()
    if (!['driving', 'walking', 'bicycling', 'transit'].includes(mode)) return false

    const ready = await ensureRouteServices()
    if (!ready) return false

    const origin = toAmapLngLat(route && route.origin_location)
    const destination = toAmapLngLat(route && route.destination_location)
    if (!origin || !destination) return false

    clearRouteServices()

    const checkpoints = buildSearchCheckpoints(route)

    if (mode === 'driving') {
      const wpLocs = Array.isArray(route && route.waypoint_locations)
        ? route.waypoint_locations
        : []
      const waypointPoints = wpLocs
        .map(function (loc) { return toAmapLngLat(loc) })
        .filter(function (p) { return !!p })
      return await doDrivingSearchWithWaypoints(
        amapRouteServices.driving, origin, destination, waypointPoints
      )
    }

    if (mode === 'walking') {
      return await drawByOfficialLegs('walking', checkpoints, '')
    }

    if (mode === 'bicycling') {
      return await drawByOfficialLegs('riding', checkpoints, '')
    }

    if (mode === 'transit') {
      const transitCity = inferTransitCity(route)
      return await drawByOfficialLegs('transit', checkpoints, transitCity)
    }

    return false
  }

  /* ── normalizeRouteOption ── */
  function normalizeRouteOption (route, option, idx) {
    const opt = option || {}
    return {
      route_index: opt.route_index != null ? opt.route_index : idx,
      summary: opt.summary || ((MODE_LABELS[route.route_mode || route.mode] || '路线') + '方案' + (idx + 1)),
      distance: opt.distance || route.distance || '',
      duration: opt.duration || route.duration || '',
      taxi_cost: opt.taxi_cost || route.taxi_cost || '',
      transfer_count: opt.transfer_count,
      steps: Array.isArray(opt.steps) ? opt.steps : (Array.isArray(route.steps) ? route.steps : []),
      polyline: opt.polyline || '',
      segments: Array.isArray(opt.segments) ? opt.segments : []
    }
  }

  function getOptionPolyline (option, route) {
    if (option && option.polyline) return option.polyline
    if (route && route.polyline) return route.polyline
    return ''
  }

  function getRouteOptions (route) {
    if (!route) return []
    if (Array.isArray(route.routes) && route.routes.length > 0) {
      return route.routes.map(function (opt, idx) {
        return normalizeRouteOption(route, opt, idx)
      })
    }
    return [normalizeRouteOption(route, {
      route_index: 0,
      summary: '推荐路线',
      distance: route.distance || '',
      duration: route.duration || '',
      taxi_cost: route.taxi_cost || '',
      steps: Array.isArray(route.steps) ? route.steps : [],
      polyline: route.polyline || '',
      segments: Array.isArray(route.segments) ? route.segments : []
    }, 0)]
  }

  /* ── 折线绘制 ── */
  function drawPolylinePath (path, style) {
    if (!path || path.length < 2) return null
    const pl = new AMap.Polyline({
      path: path,
      zIndex: style && style.zIndex != null ? style.zIndex : 80,
      strokeColor: style && style.color ? style.color : '#2563eb',
      strokeWeight: style && style.weight != null ? style.weight : 6,
      strokeOpacity: style && style.opacity != null ? style.opacity : 0.9,
      strokeStyle: style && style.dashed ? 'dashed' : 'solid',
      strokeDasharray: style && style.dashed ? [10, 8] : [0, 0],
      showDir: !!(style && style.showDir),
      isOutline: !!(style && style.isOutline),
      outlineColor: style && style.outlineColor ? style.outlineColor : '#ffffff',
      borderWeight: style && style.borderWeight != null ? style.borderWeight : 0,
      lineJoin: 'round',
      lineCap: 'round'
    })
    amapInstance.add(pl)
    amapPolylines.push(pl)
    return pl
  }

  function drawPolylinePaths (paths, style) {
    if (!Array.isArray(paths) || paths.length === 0) return
    paths.forEach(function (path) { drawPolylinePath(path, style) })
  }

  function flattenPolylinePaths (paths) {
    if (!Array.isArray(paths) || paths.length === 0) return []
    const points = []
    paths.forEach(function (path) {
      if (!Array.isArray(path) || path.length === 0) return
      path.forEach(function (p, idx) {
        if (!p) return
        if (points.length > 0 && idx === 0) {
          const prev = points[points.length - 1]
          if (prev && prev.lng === p.lng && prev.lat === p.lat) return
        }
        points.push(p)
      })
    })
    return points
  }

  /* ── 路段样式 ── */
  function styleForSegment (seg, busColorMap, usedBusColorCountRef) {
    const segType = (seg.type || '').toLowerCase()

    if (segType === 'walking') {
      return { color: '#64748b', weight: 5, opacity: 0.9, dashed: true, zIndex: 92 }
    }

    if (segType === 'bus') {
      const busPalette = ['#2563eb', '#16a34a', '#d97706', '#db2777', '#7c3aed', '#0891b2']
      const lineName = seg.line_name || ('bus_' + usedBusColorCountRef.count)
      if (!busColorMap[lineName]) {
        busColorMap[lineName] = busPalette[usedBusColorCountRef.count % busPalette.length]
        usedBusColorCountRef.count += 1
      }
      return { color: busColorMap[lineName], weight: 7, opacity: 0.96, dashed: false, zIndex: 96 }
    }

    return { color: '#2563eb', weight: 7, opacity: 0.94, dashed: false, zIndex: 95, showDir: true }
  }

  /* ── buildRouteCheckpoints ── */
  function buildRouteCheckpoints (route) {
    const checkpoints = []
    const origin = parseLngLat(route && route.origin_location)
    if (origin) checkpoints.push(origin)

    const wpLocs = Array.isArray(route && route.waypoint_locations)
      ? route.waypoint_locations
      : []
    wpLocs.forEach(function (loc) {
      const wp = parseLngLat(loc)
      if (wp) checkpoints.push(wp)
    })

    const dest = parseLngLat(route && route.destination_location)
    if (dest) checkpoints.push(dest)
    return checkpoints
  }

  /* ── splitPolylineByCheckpoints ── */
  function splitPolylineByCheckpoints (paths, checkpoints) {
    const points = flattenPolylinePaths(paths)
    if (points.length < 2 || !Array.isArray(checkpoints) || checkpoints.length < 2) {
      return []
    }

    const splitIndices = [0]
    let cursor = 0
    for (let i = 1; i < checkpoints.length - 1; i++) {
      const idx = findNearestPathIndex(points, checkpoints[i], cursor)
      if (idx <= cursor || idx >= points.length - 1) continue
      splitIndices.push(idx)
      cursor = idx
    }
    splitIndices.push(points.length - 1)

    const legPaths = []
    for (let j = 1; j < splitIndices.length; j++) {
      const start = splitIndices[j - 1]
      const end = splitIndices[j]
      if (end - start < 1) continue
      const leg = points.slice(start, end + 1)
      if (leg.length >= 2) legPaths.push(leg)
    }
    return legPaths
  }

  /* ── drawWaypointLegs ── */
  function drawWaypointLegs (paths, route) {
    const checkpoints = buildRouteCheckpoints(route)
    if (checkpoints.length < 3) return false

    const legPaths = splitPolylineByCheckpoints(paths, checkpoints)
    if (!legPaths.length) return false

    const legPalette = ['#2563eb', '#16a34a', '#d97706', '#db2777', '#7c3aed', '#0891b2']
    legPaths.forEach(function (leg, idx) {
      drawPolylinePath(leg, {
        color: legPalette[idx % legPalette.length],
        weight: 7,
        opacity: 0.95,
        dashed: false,
        zIndex: 95,
        showDir: true
      })
    })
    return true
  }

  /* ── drawInactiveRoute ── */
  function drawInactiveRoute (option, route) {
    const polyline = getOptionPolyline(option, route)
    const paths = parsePolylineToPaths(polyline)
    drawPolylinePaths(paths, {
      color: '#94a3b8',
      weight: 4,
      opacity: 0.45,
      dashed: false,
      zIndex: 70
    })
  }

  /* ── drawActiveRoute ── */
  function drawActiveRoute (option, route) {
    if (!option) return

    const mode = String((route && (route.route_mode || route.mode)) || '').toLowerCase()
    const hasWaypoints = Array.isArray(route && route.waypoint_locations) &&
        route.waypoint_locations.length > 0

    if (hasWaypoints && mode !== 'transit') {
      const waypointPaths = parsePolylineToPaths(getOptionPolyline(option, route))
      if (drawWaypointLegs(waypointPaths, route)) return
    }

    const busColorMap = {}
    const usedBusColorCountRef = { count: 0 }

    if (Array.isArray(option.segments) && option.segments.length > 0) {
      let hasValidSegment = false
      option.segments.forEach(function (seg) {
        const segPaths = parsePolylineToPaths(seg.polyline || '')
        if (!segPaths.length) return
        hasValidSegment = true
        const style = styleForSegment(seg, busColorMap, usedBusColorCountRef)
        drawPolylinePaths(segPaths, style)
      })
      if (hasValidSegment) return
    }

    const polyline = getOptionPolyline(option, route)
    const paths = parsePolylineToPaths(polyline)
    drawPolylinePaths(paths, {
      color: '#2563eb',
      weight: 7,
      opacity: 0.94,
      dashed: false,
      zIndex: 95,
      showDir: true
    })
  }

  /* ── addRouteMarker ── */
  function addRouteMarker (position, htmlText) {
    if (!position) return
    const marker = new AMap.Marker({
      position: position,
      content: htmlText,
      anchor: 'center',
      offset: new AMap.Pixel(0, 0),
      zIndex: 120
    })
    amapInstance.add(marker)
    amapMarkers.push(marker)
  }

  /* ── formatDurationMinutes / formatDistanceKm ── */
  function formatDurationMinutes (duration) {
    const mins = Math.round(parseFloat(duration || 0) / 60)
    return isNaN(mins) || mins <= 0 ? '' : (mins + '分钟')
  }

  function formatDistanceKm (distance) {
    const km = (parseFloat(distance || 0) / 1000).toFixed(1)
    return isNaN(parseFloat(km)) || parseFloat(km) <= 0 ? '' : (km + '公里')
  }

  /* ── buildSelectedRoutePayload ── */
  function buildSelectedRoutePayload (route) {
    const base = route || {}
    const options = getRouteOptions(base)
    let idx = Number(selectedRouteIndex.value) || 0
    if (idx < 0 || idx >= options.length) idx = 0
    const active = options[idx] || {}

    const mergedSteps = Array.isArray(active.steps) && active.steps.length > 0
      ? active.steps
      : (Array.isArray(base.steps) ? base.steps : [])

    return {
      status: base.status || 'success',
      origin_name: base.origin_name || '',
      destination_name: base.destination_name || '',
      origin_location: base.origin_location || '',
      destination_location: base.destination_location || '',
      route_mode: base.route_mode || base.mode || 'driving',
      waypoints: Array.isArray(base.waypoints) ? base.waypoints : [],
      waypoint_locations: Array.isArray(base.waypoint_locations) ? base.waypoint_locations : [],
      distance: active.distance || base.distance || '',
      duration: active.duration || base.duration || '',
      taxi_cost: active.taxi_cost || base.taxi_cost || '',
      steps: mergedSteps,
      route_index: active.route_index != null ? active.route_index : idx
    }
  }

  /* ── sendPlannedRouteToBackend ── */
  function sendPlannedRouteToBackend (route) {
    if (!isWsConnected()) return
    const payload = buildSelectedRoutePayload(route)
    wsSend({
      type: 'nav_js_route_result',
      route_result: payload
    })
  }

  /* ── renderRouteSelector ── */
  function renderRouteSelector (route, optionsBoxEl) {
    if (!optionsBoxEl) return

    const options = getRouteOptions(route)
    if (options.length <= 1) {
      optionsBoxEl.style.display = 'none'
      optionsBoxEl.innerHTML = ''
      selectedRouteIndex.value = 0
      return
    }

    if (selectedRouteIndex.value >= options.length) {
      selectedRouteIndex.value = 0
    }

    const modeLabel = MODE_LABELS[route.route_mode || route.mode] || '路线'
    let html = '<div class="route-options-title">可选' + modeLabel + '方案（共' + options.length + '条）</div>'
    html += '<div class="route-option-list">'

    options.forEach(function (opt, idx) {
      const title = opt.summary || (modeLabel + '方案' + (idx + 1))
      const d = formatDistanceKm(opt.distance)
      const t = formatDurationMinutes(opt.duration)
      const extra = []
      if (d) extra.push(d)
      if (t) extra.push(t)
      if (opt.transfer_count != null && String(opt.transfer_count) !== '') {
        extra.push('换乘' + opt.transfer_count + '次')
      }
      const cls = idx === selectedRouteIndex.value ? 'route-option-chip active' : 'route-option-chip'
      html += '<button class="' + cls + '" data-route-idx="' + idx + '">' + title
      if (extra.length > 0) {
        html += ' · ' + extra.join(' / ')
      }
      html += '</button>'
    })

    html += '</div>'
    optionsBoxEl.innerHTML = html
    optionsBoxEl.style.display = 'block'

    optionsBoxEl.querySelectorAll('[data-route-idx]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const idx = parseInt(this.getAttribute('data-route-idx'), 10)
        if (isNaN(idx)) return
        selectedRouteIndex.value = idx
        renderRouteSelector(route, optionsBoxEl)
        showRouteOnMap(route, optionsBoxEl)
        sendPlannedRouteToBackend(route)
      })
    })
  }

  /* ── showRouteOnMap ── */
  async function showRouteOnMap (route, optionsBoxEl) {
    const map = ensureMap()
    if (!map) return

    latestRoutePayload.value = route
    renderRouteSelector(route, optionsBoxEl)
    clearMapOverlays()

    const routeOptions = getRouteOptions(route)
    if (!routeOptions.length) return
    if (selectedRouteIndex.value >= routeOptions.length) {
      selectedRouteIndex.value = 0
    }

    const selectedOption = routeOptions[selectedRouteIndex.value]

    const originLngLat = parseLngLat(route.origin_location)
    const destLngLat = parseLngLat(route.destination_location)

    if (originLngLat) {
      addRouteMarker(
        originLngLat,
        '<div style="background:#0f766e;color:#fff;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:bold;white-space:nowrap;">起 ' + (route.origin_name || '') + '</div>'
      )
    }

    if (destLngLat) {
      addRouteMarker(
        destLngLat,
        '<div style="background:#b45309;color:#fff;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:bold;white-space:nowrap;">终 ' + (route.destination_name || '') + '</div>'
      )
    }

    const wpLocs = Array.isArray(route.waypoint_locations) ? route.waypoint_locations : []
    const wpNames = Array.isArray(route.waypoints) ? route.waypoints : []
    wpLocs.forEach(function (loc, idx) {
      const lngLat = parseLngLat(loc)
      if (!lngLat) return
      addRouteMarker(
        lngLat,
        '<div style="background:#7c3aed;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold;white-space:nowrap;">途' + (idx + 1) + ' ' + (wpNames[idx] || '') + '</div>'
      )
    })

    let serviceDrawn = false
    if (!route || !route._service_already_tried) {
      serviceDrawn = await drawRouteByAmapNavigationService(route)
    }
    if (!serviceDrawn) {
      routeOptions.forEach(function (opt, idx) {
        if (idx === selectedRouteIndex.value) return
        drawInactiveRoute(opt, route)
      })
      drawActiveRoute(selectedOption, route)
      const fitItems = amapMarkers.concat(amapPolylines)
      if (fitItems.length > 0) {
        map.setFitView(fitItems, false, [70, 70, 70, 70])
      }
    } else {
      map.setFitView(undefined, false, [70, 70, 70, 70])
    }
  }

  /* ── showCandidatesOnMap ── */
  function showCandidatesOnMap (candidates) {
    const map = ensureMap()
    if (!map) return
    clearMapOverlays()

    const bounds = []
    const colors = {
      origin: '#0f766e',
      destination: '#b45309',
      waypoint: '#7c3aed',
      other: '#2563eb'
    }

    candidates.forEach(function (poi, i) {
      const lngLat = parseLngLat(poi.location)
      if (!lngLat) return
      const group = poi.selection_group || 'other'
      const color = colors[group] || '#2563eb'
      const label = group === 'origin'
        ? '起'
        : (group === 'destination' ? '终' : (group === 'waypoint' ? '途' : ''))

      const marker = new AMap.Marker({
        position: lngLat,
        content: '<div style="background:' + color + ';color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold;white-space:nowrap;cursor:pointer;">' + label + (i + 1) + ' ' + (poi.name || '') + '</div>',
        offset: new AMap.Pixel(-40, -12)
      })
      map.add(marker)
      amapMarkers.push(marker)
      bounds.push(lngLat)
    })

    if (bounds.length > 0) {
      map.setFitView(amapMarkers, false, [60, 60, 60, 60])
    }
  }

  /* ── destroyMap ── */
  function destroyMap () {
    if (amapInstance && typeof amapInstance.destroy === 'function') {
      try { amapInstance.destroy() } catch (e) {
        console.warn('[MAP] destroy failed:', e)
      }
      amapInstance = null
    }
  }

  /* ── return ── */
  return {
    amapReady,
    mapStatus,
    mapStatusMessage,
    selectedRouteIndex,
    latestRoutePayload,
    initAMap,
    setMapContainer,
    ensureMap,
    isAmapReady,
    getAmapReadyState,
    clearMapOverlays,
    showRouteOnMap,
    showCandidatesOnMap,
    planRouteByJsApiOnce,
    buildSelectedRoutePayload,
    sendPlannedRouteToBackend,
    renderRouteSelector,
    formatDurationMinutes,
    formatDistanceKm,
    getRouteOptions,
    destroyMap,
    MODE_LABELS
  }
}
