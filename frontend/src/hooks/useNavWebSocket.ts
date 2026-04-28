import { useCallback, useEffect, useRef, useState } from 'react'
import { getWsUrl } from '../config/api'
import type {
  LocalizationStatus,
  NavigationStatus,
  NavWebSocketEvent,
  RobotPose,
} from '../types/navState'

type NavWebSocketState = {
  connected: boolean
  robotPose: RobotPose | null
  localizationStatus: LocalizationStatus | null
  navigationStatus: NavigationStatus | null
  lastMessageAt: number | null
}

export function useNavWebSocket() {
  const [state, setState] = useState<NavWebSocketState>({
    connected: false,
    robotPose: null,
    localizationStatus: null,
    navigationStatus: null,
    lastMessageAt: null,
  })

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<number | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const connectionIdRef = useRef(0)

  const connect = useCallback(() => {
    const rs = wsRef.current?.readyState
    if (rs === WebSocket.OPEN || rs === WebSocket.CONNECTING) return

    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
      wsRef.current.close(1000)
      wsRef.current = null
    }

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }

    connectionIdRef.current += 1
    const currentConnectionId = connectionIdRef.current

    const ws = new WebSocket(getWsUrl('/ws/event'))
    wsRef.current = ws

    ws.onopen = () => {
      if (currentConnectionId !== connectionIdRef.current) return
      reconnectAttemptsRef.current = 0
      setState((prev) => ({ ...prev, connected: true }))
    }

    ws.onmessage = (event) => {
      if (currentConnectionId !== connectionIdRef.current) return

      try {
        const message = JSON.parse(event.data)
        if (!message?.type || typeof message.type !== 'string' || !message.type.startsWith('nav.')) {
          return
        }

        const navEvent = message as NavWebSocketEvent
        setState((prev) => {
          if (navEvent.type === 'nav.robot_pose') {
            return { ...prev, robotPose: navEvent.data, lastMessageAt: Date.now() }
          }
          if (navEvent.type === 'nav.localization_status') {
            return { ...prev, localizationStatus: navEvent.data, lastMessageAt: Date.now() }
          }
          if (navEvent.type === 'nav.navigation_status') {
            return { ...prev, navigationStatus: navEvent.data, lastMessageAt: Date.now() }
          }
          return prev
        })
      } catch (error) {
        console.error('解析导航 WebSocket 消息失败:', error)
      }
    }

    ws.onclose = (event) => {
      if (currentConnectionId !== connectionIdRef.current) return
      setState((prev) => ({ ...prev, connected: false }))

      if (event.code === 1000) return

      if (reconnectAttemptsRef.current < 10) {
        reconnectAttemptsRef.current += 1
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current - 1), 10000)
        reconnectTimeoutRef.current = window.setTimeout(connect, delay)
      }
    }

    ws.onerror = () => {
      if (currentConnectionId !== connectionIdRef.current) return
      setState((prev) => ({ ...prev, connected: false }))
    }
  }, [])

  const disconnect = useCallback(() => {
    connectionIdRef.current += 1
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close(1000)
      wsRef.current = null
    }
    setState((prev) => ({ ...prev, connected: false }))
  }, [])

  useEffect(() => {
    connect()
    return disconnect
  }, [connect, disconnect])

  return {
    ...state,
    setInitialState: (next: {
      robotPose?: RobotPose | null
      localizationStatus?: LocalizationStatus | null
      navigationStatus?: NavigationStatus | null
    }) => {
      setState((prev) => ({
        ...prev,
        robotPose: next.robotPose ?? prev.robotPose,
        localizationStatus: next.localizationStatus ?? prev.localizationStatus,
        navigationStatus: next.navigationStatus ?? prev.navigationStatus,
      }))
    },
    connect,
    disconnect,
  }
}
