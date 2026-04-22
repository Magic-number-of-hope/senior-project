export function useLocation (sendLocationUpdate, amapReadyFn) {
  function uploadBrowserLocation (force) {
    if (!navigator.geolocation) {
      console.warn('[LOCATION] browser geolocation not supported')
      return
    }
    navigator.geolocation.getCurrentPosition(
      function (pos) {
        const lng = Number(pos.coords.longitude).toFixed(6)
        const lat = Number(pos.coords.latitude).toFixed(6)
        const payload = {
          location: `${lng},${lat}`,
          name: '当前位置',
          source: 'browser',
          accuracy: Math.round(pos.coords.accuracy || 0),
          timestamp: pos.timestamp || Date.now()
        }
        sendLocationUpdate(payload, !!force)
        console.log('[LOCATION] uploaded(browser)', payload.location)
      },
      function (err) {
        console.warn('[LOCATION] getCurrentPosition failed:', err && err.message ? err.message : err)
      },
      { enableHighAccuracy: true, timeout: 6000, maximumAge: 120000 }
    )
  }

  function tryUploadCurrentLocation (force) {
    if (amapReadyFn() && window.AMap) {
      try {
        const geolocation = new window.AMap.Geolocation({
          enableHighAccuracy: true,
          timeout: 8000,
          convert: true,
          showButton: false
        })
        geolocation.getCurrentPosition(function (status, result) {
          if (status === 'complete' && result && result.position) {
            const lng = Number(result.position.lng).toFixed(6)
            const lat = Number(result.position.lat).toFixed(6)
            const payload = {
              location: `${lng},${lat}`,
              name: '当前位置',
              source: 'amap',
              accuracy: Math.round(result.accuracy || 0),
              timestamp: Date.now()
            }
            sendLocationUpdate(payload, !!force)
            console.log('[LOCATION] uploaded(amap)', payload.location)
            return
          }
          uploadBrowserLocation(force)
        })
        return
      } catch (err) {
        console.warn('[LOCATION] AMap geolocation failed, fallback browser:', err)
      }
    }
    uploadBrowserLocation(force)
  }

  return { tryUploadCurrentLocation }
}
