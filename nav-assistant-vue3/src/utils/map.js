/**
 * Parse "lng,lat" string or [lng,lat] array into [lng, lat] pair
 */
export function parseLngLat(input) {
  if (!input) return null
  if (Array.isArray(input) && input.length >= 2) {
    return [parseFloat(input[0]), parseFloat(input[1])]
  }
  if (typeof input === 'string') {
    const parts = input.split(',')
    if (parts.length >= 2) {
      const lng = parseFloat(parts[0])
      const lat = parseFloat(parts[1])
      if (!isNaN(lng) && !isNaN(lat)) return [lng, lat]
    }
  }
  if (typeof input === 'object' && input.lng != null && input.lat != null) {
    return [parseFloat(input.lng), parseFloat(input.lat)]
  }
  return null
}

/**
 * Convert to AMap.LngLat object
 */
export function toAmapLngLat(point) {
  const p = parseLngLat(point)
  if (!p || !window.AMap) return null
  return new AMap.LngLat(p[0], p[1])
}

/**
 * Convert LngLat object to "lng,lat" string
 */
export function lngLatObjToPairString(point) {
  if (!point) return ''
  const lng = typeof point.getLng === 'function' ? point.getLng() : point.lng
  const lat = typeof point.getLat === 'function' ? point.getLat() : point.lat
  if (lng == null || lat == null) return ''
  return Number(lng).toFixed(6) + ',' + Number(lat).toFixed(6)
}

/**
 * Parse polyline string to paths array
 */
export function parsePolylineToPaths(polyline) {
  if (!polyline || typeof polyline !== 'string') return []
  return polyline.split('|').map(seg => {
    return seg.split(';').map(pair => {
      const [lng, lat] = pair.split(',').map(Number)
      return !isNaN(lng) && !isNaN(lat) ? [lng, lat] : null
    }).filter(Boolean)
  }).filter(p => p.length > 0)
}

/**
 * Get route options from route data
 */
export function getRouteOptions(route) {
  if (!route) return []
  if (Array.isArray(route.routes) && route.routes.length > 0) return route.routes
  if (Array.isArray(route.options) && route.options.length > 0) return route.options
  return [route]
}

/**
 * Get polyline from option or route
 */
export function getOptionPolyline(option, route) {
  if (!option && !route) return ''
  if (option && option.polyline) return option.polyline
  if (route && route.polyline) return route.polyline
  if (option && Array.isArray(option.segments)) {
    return option.segments.map(s => s.polyline || '').filter(Boolean).join('|')
  }
  return ''
}

/**
 * Extract step polyline
 */
export function stepToPolyline(step) {
  if (!step) return ''
  if (Array.isArray(step.path) && step.path.length > 0) {
    return step.path.map(lngLatObjToPairString).filter(Boolean).join(';')
  }
  if (typeof step.polyline === 'string' && step.polyline) return step.polyline
  return ''
}

/**
 * Normalize JS API route result
 */
export function normalizeJsApiRouteResult(mode, result, baseRoute) {
  const routesRaw = Array.isArray(result?.routes) ? result.routes : []
  if (!routesRaw.length) return null

  const routeMode = mode === 'bicycling' ? 'bicycling' : mode
  const options = routesRaw.map((r, idx) => {
    const stepsRaw = Array.isArray(r.steps) ? r.steps : []
    const stepList = stepsRaw.map(s => ({
      instruction: s.instruction || s.action || '',
      distance: String(s.distance ?? ''),
    }))
    const polylineSegments = stepsRaw.map(stepToPolyline).filter(Boolean)
    const routePolyline = polylineSegments.join('|')
    const duration = r.time ?? r.duration
    return {
      route_index: idx,
      summary: `${routeMode}方案${idx + 1}`,
      distance: String(r.distance ?? ''),
      duration: String(duration ?? ''),
      taxi_cost: String(result?.taxi_cost ?? baseRoute?.taxi_cost ?? ''),
      steps: stepList,
      polyline: routePolyline,
      segments: routePolyline ? [{ type: routeMode, line_name: routeMode, polyline: routePolyline }] : [],
    }
  })

  if (!options.length) return null
  const best = options[0]

  return {
    ...(baseRoute || {}),
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
    _skip_service_search: true,
    _service_already_tried: true,
  }
}
