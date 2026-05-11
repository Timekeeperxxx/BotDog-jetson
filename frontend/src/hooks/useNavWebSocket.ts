import { useCallback, useEffect, useRef, useState } from 'react'
import { useEventStream } from '../runtime/EventStreamProvider'
import type {
  GlobalPath,
  LocalizationStatus,
  NavigationStatus,
  NavWebSocketEvent,
  RobotPose,
} from '../types/navState'

type NavWebSocketState = {
  robotPose: RobotPose | null
  globalPath: GlobalPath | null
  localizationStatus: LocalizationStatus | null
  navigationStatus: NavigationStatus | null
  lastMessageAt: number | null
}

export function useNavWebSocket() {
  // /ws/event 由 EventStreamProvider 统一管理，这里只派生导航状态。
  const stream = useEventStream()
  const [state, setState] = useState<NavWebSocketState>({
    robotPose: null,
    globalPath: null,
    localizationStatus: null,
    navigationStatus: null,
    lastMessageAt: null,
  })
  const processedEnvelopeIdRef = useRef(0)
  const initializedRef = useRef(false)

  useEffect(() => {
    const latestEnvelope = stream.envelopes[stream.envelopes.length - 1] ?? null

    if (!initializedRef.current) {
      processedEnvelopeIdRef.current = latestEnvelope?.id ?? 0
      initializedRef.current = true
      return
    }

    const pending = stream.envelopes.filter((envelope) => envelope.id > processedEnvelopeIdRef.current)
    if (pending.length === 0) {
      return
    }

    pending.forEach((envelope) => {
      const message = envelope.message as { type?: string; data?: unknown }
      if (!message?.type || typeof message.type !== 'string' || !message.type.startsWith('nav.')) {
        return
      }

      const navEvent = message as NavWebSocketEvent
      setState((prev) => {
        if (navEvent.type === 'nav.robot_pose') {
          return { ...prev, robotPose: navEvent.data, lastMessageAt: envelope.receivedAt }
        }
        if (navEvent.type === 'nav.global_path') {
          return { ...prev, globalPath: navEvent.data, lastMessageAt: envelope.receivedAt }
        }
        if (navEvent.type === 'nav.localization_status') {
          return { ...prev, localizationStatus: navEvent.data, lastMessageAt: envelope.receivedAt }
        }
        if (navEvent.type === 'nav.navigation_status') {
          return { ...prev, navigationStatus: navEvent.data, lastMessageAt: envelope.receivedAt }
        }
        return prev
      })
    })

    processedEnvelopeIdRef.current = pending[pending.length - 1].id
  }, [stream.envelopes])

  const setInitialState = useCallback((next: {
    robotPose?: RobotPose | null
    globalPath?: GlobalPath | null
    localizationStatus?: LocalizationStatus | null
    navigationStatus?: NavigationStatus | null
  }) => {
    setState((prev) => ({
      ...prev,
      robotPose: Object.prototype.hasOwnProperty.call(next, 'robotPose') ? next.robotPose ?? null : prev.robotPose,
      globalPath: Object.prototype.hasOwnProperty.call(next, 'globalPath') ? next.globalPath ?? null : prev.globalPath,
      localizationStatus: Object.prototype.hasOwnProperty.call(next, 'localizationStatus') ? next.localizationStatus ?? null : prev.localizationStatus,
      navigationStatus: Object.prototype.hasOwnProperty.call(next, 'navigationStatus') ? next.navigationStatus ?? null : prev.navigationStatus,
    }))
  }, [])

  const connect = useCallback(() => {
    stream.connect()
  }, [stream])

  const disconnect = useCallback(() => {
    stream.disconnect()
  }, [stream])

  return {
    connected: stream.connected,
    robotPose: state.robotPose,
    globalPath: state.globalPath,
    localizationStatus: state.localizationStatus,
    navigationStatus: state.navigationStatus,
    lastMessageAt: state.lastMessageAt,
    setInitialState,
    connect,
    disconnect,
  }
}
