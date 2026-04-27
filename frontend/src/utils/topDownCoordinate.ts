import type { PcdBounds } from '../types/pcdMap'

const MIN_RANGE = 0.0001

export function getTopDownScale(
  bounds: PcdBounds,
  canvasWidth: number,
  canvasHeight: number,
  padding = 30,
) {
  const usableWidth = Math.max(1, canvasWidth - padding * 2)
  const usableHeight = Math.max(1, canvasHeight - padding * 2)
  const rangeX = Math.max(MIN_RANGE, bounds.max_x - bounds.min_x)
  const rangeY = Math.max(MIN_RANGE, bounds.max_y - bounds.min_y)

  return Math.min(usableWidth / rangeX, usableHeight / rangeY)
}

export function mapToCanvas(
  x: number,
  y: number,
  bounds: PcdBounds,
  canvasWidth: number,
  canvasHeight: number,
  padding = 30,
) {
  const scale = getTopDownScale(bounds, canvasWidth, canvasHeight, padding)

  return {
    x: padding + (x - bounds.min_x) * scale,
    y: canvasHeight - padding - (y - bounds.min_y) * scale,
  }
}

export function canvasToMap(
  canvasX: number,
  canvasY: number,
  bounds: PcdBounds,
  canvasWidth: number,
  canvasHeight: number,
  padding = 30,
) {
  const scale = getTopDownScale(bounds, canvasWidth, canvasHeight, padding)

  return {
    x: bounds.min_x + (canvasX - padding) / scale,
    y: bounds.min_y + (canvasHeight - padding - canvasY) / scale,
  }
}
