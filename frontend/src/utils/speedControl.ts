export const DEFAULT_LINEAR_SPEED = 0.3
export const DEFAULT_TURN_SPEED = 0.5
export const SPEED_STEP = 0.1
export const MAX_LINEAR_SPEED = 0.6
export const MAX_TURN_SPEED = 0.8

export function clampSpeed(value: number, limit: number) {
  return Math.max(0, Math.min(limit, Number(value.toFixed(1))))
}

export function isArrowSpeedKey(key: string) {
  return ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(key)
}

export function formatSpeed(value: number) {
  return value.toFixed(1)
}
