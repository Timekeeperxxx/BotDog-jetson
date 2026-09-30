import type { PcdBounds } from '../types/pcdMap'
import { canvasToMap, mapToCanvas } from './topDownCoordinate'

export function getMapExtents(bounds: PcdBounds | null) {
  if (!bounds || ![bounds.min_x, bounds.max_x, bounds.min_y, bounds.max_y].every(Number.isFinite)) return null
  const x = bounds.max_x - bounds.min_x
  const y = bounds.max_y - bounds.min_y
  if (x < 0 || y < 0 || !Number.isFinite(x * y)) return null
  return { x, y, area: x * y }
}

function ticks(min: number, max: number, pixels: number) {
  const target = (max - min) / Math.max(2, Math.floor(pixels / 65))
  if (!Number.isFinite(target) || target <= 0) return []
  const power = 10 ** Math.floor(Math.log10(target))
  const step = ([10, 5, 2, 1].find(value => value * power <= target) ?? 1) * power
  const first = Math.ceil(min / step)
  const last = Math.floor(max / step)
  return Array.from({ length: Math.max(0, Math.min(100, last - first + 1)) }, (_, index) => {
    const value = (first + index) * step
    return { value, label: value === 0 ? '0' : value.toFixed(Math.min(6, Math.max(0, -Math.floor(Math.log10(step))))) }
  })
}

// Existing map orientation: +X up, +Y left. All positions use CSS pixels,
// so browser/DPR scaling does not change the physical distances on the rulers.
export function getTopDownRulers(bounds: PcdBounds, width: number, height: number, padding: number,
  view: { zoom: number; panX: number; panY: number }) {
  if (!getMapExtents(bounds) || width <= padding * 2 || height <= padding * 2
    || ![view.zoom, view.panX, view.panY].every(Number.isFinite) || view.zoom <= 0) return { x: [], y: [] }
  const inverse = (x: number, y: number) => canvasToMap(
    (x - width / 2 - view.panX) / view.zoom + width / 2,
    (y - height / 2 - view.panY) / view.zoom + height / 2,
    bounds, width, height, padding,
  )
  const topLeft = inverse(padding, padding)
  const bottomRight = inverse(width - padding, height - padding)
  return {
    x: ticks(bottomRight.x, topLeft.x, height - padding * 2).map(tick => ({
      ...tick,
      position: (mapToCanvas(tick.value, bounds.min_y, bounds, width, height, padding).y - height / 2) * view.zoom + height / 2 + view.panY,
    })),
    y: ticks(bottomRight.y, topLeft.y, width - padding * 2).map(tick => ({
      ...tick,
      position: (mapToCanvas(bounds.min_x, tick.value, bounds, width, height, padding).x - width / 2) * view.zoom + width / 2 + view.panX,
    })),
  }
}
