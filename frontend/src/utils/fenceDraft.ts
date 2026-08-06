export type FenceDraftPoint = { x: number; y: number; z: number }

export type FenceDraftResult = {
  start: FenceDraftPoint | null
  completed: { start: FenceDraftPoint; end: FenceDraftPoint } | null
}

/**
 * Consume one ground click for the two-click fence workflow. Very short
 * segments keep the existing first point so an accidental double-click does
 * not create an unusable fence.
 */
export function advanceFenceDraft(
  start: FenceDraftPoint | null,
  point: FenceDraftPoint,
  minimumLengthMeters = 0.01,
): FenceDraftResult {
  if (start === null) {
    return { start: point, completed: null }
  }

  if (Math.hypot(point.x - start.x, point.y - start.y) <= minimumLengthMeters) {
    return { start, completed: null }
  }

  return {
    start: null,
    completed: { start, end: point },
  }
}
