// Point sizes and pointer positions stay in CSS pixels. Only the backing buffer
// uses this ratio; a pixel budget bounds fill cost on large/high-density screens.
export const CANVAS_PIXEL_RATIO_LIMIT = 2
export const CANVAS_PIXEL_BUDGET = 4_000_000

export function getCanvasPixelRatio(width: number, height: number, deviceRatio: number) {
  const ratio = Number.isFinite(deviceRatio) && deviceRatio > 0 ? deviceRatio : 1
  const area = Math.max(1, width) * Math.max(1, height)
  return Math.min(ratio, CANVAS_PIXEL_RATIO_LIMIT, Math.sqrt(CANVAS_PIXEL_BUDGET / area))
}

/** Observe layout and display density, including moving between monitors without
 * changing the element's CSS size. Re-arm the query after each density change. */
export function observeCanvasViewport(host: HTMLElement, update: () => void) {
  let densityQuery: MediaQueryList | undefined
  const watchDensity = () => {
    densityQuery?.removeEventListener('change', onDensityChange)
    densityQuery = window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`)
    densityQuery.addEventListener('change', onDensityChange)
  }
  const onDensityChange = () => {
    watchDensity()
    update()
  }
  const observer = new ResizeObserver(update)
  observer.observe(host)
  watchDensity()
  window.addEventListener('resize', update)
  update()
  return () => {
    observer.disconnect()
    densityQuery?.removeEventListener('change', onDensityChange)
    window.removeEventListener('resize', update)
  }
}
