import { useCallback, useEffect, useRef, useState } from 'react'
import type { RobotCommand, RobotCommandOptions } from './useRobotControl'
import {
  DEFAULT_LINEAR_SPEED,
  DEFAULT_TURN_SPEED,
  MAX_LINEAR_SPEED,
  MAX_TURN_SPEED,
  SPEED_STEP,
  clampSpeed,
  isArrowSpeedKey,
} from '../utils/speedControl'
import { resolveRobotCommandFromKey } from '../utils/keyboardRobotControl'

type UseKeyboardRobotControlOptions = {
  canOperate: boolean
  enabled: boolean
  isControlling: boolean
  currentCmd: RobotCommand | null
  startCommand: (cmd: RobotCommand, options?: RobotCommandOptions) => void
  stopCommand: () => void
}

export function useKeyboardRobotControl({
  canOperate,
  enabled,
  isControlling,
  currentCmd,
  startCommand,
  stopCommand,
}: UseKeyboardRobotControlOptions) {
  const [linearSpeed, setLinearSpeed] = useState(DEFAULT_LINEAR_SPEED)
  const [turnSpeed, setTurnSpeed] = useState(DEFAULT_TURN_SPEED)
  const linearSpeedRef = useRef(DEFAULT_LINEAR_SPEED)
  const turnSpeedRef = useRef(DEFAULT_TURN_SPEED)

  const resetSpeeds = useCallback(() => {
    linearSpeedRef.current = DEFAULT_LINEAR_SPEED
    turnSpeedRef.current = DEFAULT_TURN_SPEED
    setLinearSpeed(DEFAULT_LINEAR_SPEED)
    setTurnSpeed(DEFAULT_TURN_SPEED)
  }, [])

  const adjustSpeed = useCallback((key: string) => {
    let nextLinearSpeed = linearSpeedRef.current
    let nextTurnSpeed = turnSpeedRef.current

    if (key === 'ArrowUp') {
      nextLinearSpeed = clampSpeed(nextLinearSpeed + SPEED_STEP, MAX_LINEAR_SPEED)
    } else if (key === 'ArrowDown') {
      nextLinearSpeed = clampSpeed(nextLinearSpeed - SPEED_STEP, MAX_LINEAR_SPEED)
    } else if (key === 'ArrowLeft') {
      nextTurnSpeed = clampSpeed(nextTurnSpeed + SPEED_STEP, MAX_TURN_SPEED)
    } else if (key === 'ArrowRight') {
      nextTurnSpeed = clampSpeed(nextTurnSpeed - SPEED_STEP, MAX_TURN_SPEED)
    }

    linearSpeedRef.current = nextLinearSpeed
    turnSpeedRef.current = nextTurnSpeed
    setLinearSpeed(nextLinearSpeed)
    setTurnSpeed(nextTurnSpeed)
  }, [])

  const startKeyboardCommand = useCallback((cmd: RobotCommand | null) => {
    if (!cmd) return

    if (cmd === 'forward' || cmd === 'backward') {
      const vx = linearSpeedRef.current
      if (vx === 0) return
      startCommand(cmd, { vx })
      return
    }

    if (cmd === 'left' || cmd === 'right') {
      const vyaw = turnSpeedRef.current
      if (vyaw === 0) return
      startCommand(cmd, { vyaw })
      return
    }

    startCommand(cmd)
  }, [startCommand])

  useEffect(() => {
    if (!enabled && isControlling) stopCommand()
  }, [enabled, isControlling, stopCommand])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((event.target as HTMLElement).tagName)) return
      if (event.repeat) return
      if (!canOperate || !enabled) return

      if (isArrowSpeedKey(event.key)) {
        event.preventDefault()
        adjustSpeed(event.key)
        return
      }

      const cmd = resolveRobotCommandFromKey(event.key)

      if (cmd) {
        event.preventDefault()
        startKeyboardCommand(cmd)
      }
    }

    const handleKeyUp = (event: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((event.target as HTMLElement).tagName)) return
      if (isArrowSpeedKey(event.key)) {
        event.preventDefault()
        return
      }

      const cmd = resolveRobotCommandFromKey(event.key)

      if (cmd && currentCmd === cmd) {
        event.preventDefault()
        stopCommand()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)

    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
    }
  }, [adjustSpeed, canOperate, enabled, currentCmd, startKeyboardCommand, stopCommand])

  return {
    linearSpeed,
    resetSpeeds,
    turnSpeed,
  }
}
