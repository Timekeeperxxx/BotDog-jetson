import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from '../api/apiFetch'

type Velocity = { pitch_velocity_dps: number; yaw_velocity_dps: number }
const STOP: Velocity = { pitch_velocity_dps: 0, yaw_velocity_dps: 0 }
const SPEED = 12
// 后端0.45秒自动停转；长按定期续发，最多保留一个待发方向。
const REFRESH_MS = 200
const ARROWS = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])

function ownsArrowKeys(target: EventTarget | null) {
  return target instanceof Element && Boolean(target.closest(
    'input, textarea, select, [contenteditable]:not([contenteditable="false"]), ' +
    '[role="slider"], [role="tab"], [role="tablist"], [role="menu"], [role="dialog"], [aria-modal="true"]',
  ))
}

export function useKeyboardGimbalControl<T>({ enabled, onStatus, onError }: {
  enabled: boolean
  onStatus: (status: T) => void
  onError: (message: string) => void
}) {
  const [isJogging, setIsJogging] = useState(false)
  const keys = useRef(new Set<string>())
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)
  const desired = useRef(STOP)
  const pending = useRef(false)
  const sending = useRef(false)
  const owned = useRef(false)
  const mounted = useRef(false)
  const enabledRef = useRef(enabled)

  const clearKeys = useCallback(() => {
    keys.current.clear()
    if (timer.current !== null) clearInterval(timer.current)
    timer.current = null
    if (mounted.current) setIsJogging(false)
  }, [])

  const send = useCallback(async (velocity: Velocity) => {
    desired.current = velocity
    pending.current = true
    if (sending.current) return
    sending.current = true
    try {
      while (pending.current) {
        const next = desired.current
        pending.current = false
        try {
          const status = await apiFetch<T>('/api/v1/gimbal/jog', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(next),
            signal: AbortSignal.timeout(1500),
          })
          if (mounted.current && enabledRef.current) onStatus(status)
        } catch (reason) {
          clearKeys()
          owned.current = false
          desired.current = STOP
          // 移动失败后补发一次停止；停止失败交由后端自动停转，不无限重试。
          pending.current = Boolean(next.pitch_velocity_dps || next.yaw_velocity_dps)
          if (mounted.current && enabledRef.current) {
            onError(reason instanceof Error ? reason.message : String(reason))
          }
        }
      }
    } finally {
      sending.current = false
    }
  }, [clearKeys, onError, onStatus])

  const stop = useCallback(() => {
    const shouldStop = owned.current
    owned.current = false
    clearKeys()
    if (shouldStop) void send(STOP)
  }, [clearKeys, send])

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  useEffect(() => {
    enabledRef.current = enabled
    if (!enabled) return

    const velocity = (): Velocity => ({
      pitch_velocity_dps: (Number(keys.current.has('ArrowUp')) - Number(keys.current.has('ArrowDown'))) * SPEED,
      yaw_velocity_dps: (Number(keys.current.has('ArrowRight')) - Number(keys.current.has('ArrowLeft'))) * SPEED,
    })
    const updateDirection = () => {
      const next = velocity()
      const moving = Boolean(next.pitch_velocity_dps || next.yaw_velocity_dps)
      setIsJogging(moving)
      void send(next)
      if (timer.current !== null) clearInterval(timer.current)
      timer.current = moving ? setInterval(() => void send(velocity()), REFRESH_MS) : null
    }
    const keyDown = (event: KeyboardEvent) => {
      if (!ARROWS.has(event.key) || event.defaultPrevented || ownsArrowKeys(event.target)
          || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
      if (event.repeat && !keys.current.has(event.key)) return
      event.preventDefault()
      // 相机面板接管方向键，避免同一次按键同时改变底盘速度或滚动页面。
      event.stopImmediatePropagation()
      if (keys.current.has(event.key)) return
      owned.current = true
      keys.current.add(event.key)
      updateDirection()
    }
    const keyUp = (event: KeyboardEvent) => {
      // 即使松键时焦点已进入输入框，也必须释放之前接管的按键。
      if (!keys.current.delete(event.key)) return
      event.preventDefault()
      event.stopImmediatePropagation()
      if (keys.current.size) updateDirection()
      else stop()
    }
    const focusIn = (event: FocusEvent) => {
      if (ownsArrowKeys(event.target)) stop()
    }
    const visibility = () => { if (document.hidden) stop() }
    window.addEventListener('keydown', keyDown, true)
    window.addEventListener('keyup', keyUp, true)
    window.addEventListener('blur', stop)
    document.addEventListener('focusin', focusIn)
    document.addEventListener('visibilitychange', visibility)
    return () => {
      enabledRef.current = false
      window.removeEventListener('keydown', keyDown, true)
      window.removeEventListener('keyup', keyUp, true)
      window.removeEventListener('blur', stop)
      document.removeEventListener('focusin', focusIn)
      document.removeEventListener('visibilitychange', visibility)
      stop()
    }
  }, [enabled, send, stop])

  return { isJogging }
}
