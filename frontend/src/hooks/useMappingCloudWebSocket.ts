import { useCallback, useEffect, useRef, useState } from 'react'
import { getWsUrl } from '../config/api'
import type { MappingCloud, NavWebSocketEvent } from '../types/navState'

type MappingCloudWebSocketState = {
  connected: boolean
  mappingCloudPoints: [number, number, number][]
  liveMappingCloudPoints: [number, number, number][]
  lastMessageAt: number | null
}

export function useMappingCloudWebSocket(active: boolean) {
  const [state, setState] = useState<MappingCloudWebSocketState>({
    connected: false,
    mappingCloudPoints: [],
    liveMappingCloudPoints: [],
    lastMessageAt: null,
  })

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<number | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const connectionIdRef = useRef(0)
  const connectRef = useRef<() => void>(() => {})

  const clearMappingCloud = useCallback(() => {
    setState((prev) => ({
      ...prev,
      mappingCloudPoints: [],
      liveMappingCloudPoints: [],
      lastMessageAt: Date.now(),
    }))
  }, [])

  const disconnect = useCallback(() => {
    connectionIdRef.current += 1
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    reconnectAttemptsRef.current = 0
    if (wsRef.current) {
      wsRef.current.close(1000)
      wsRef.current = null
    }
    setState((prev) => ({
      ...prev,
      connected: false,
      mappingCloudPoints: [],
      liveMappingCloudPoints: [],
    }))
  }, [])

  const connect = useCallback(() => {
    if (!active) return

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
    const ws = new WebSocket(getWsUrl('/ws/nav-mapping-cloud'))
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
        if (message?.type !== 'nav.mapping_cloud') return

        const navEvent = message as Extract<NavWebSocketEvent, { type: 'nav.mapping_cloud' }>
        const cloud = navEvent.data as MappingCloud
        const accumulatedPts = cloud.accumulated_points ?? cloud.points
        const livePts = cloud.live_points
        setState((prev) => ({
          ...prev,
          mappingCloudPoints: accumulatedPts ?? prev.mappingCloudPoints,
          liveMappingCloudPoints: livePts ?? prev.liveMappingCloudPoints,
          lastMessageAt: Date.now(),
        }))
      } catch (error) {
        console.error('解析建图点云 WebSocket 消息失败:', error)
      }
    }

    ws.onclose = (event) => {
      if (currentConnectionId !== connectionIdRef.current) return
      setState((prev) => ({ ...prev, connected: false }))

      if (!active || event.code === 1000) return

      if (reconnectAttemptsRef.current < 10) {
        reconnectAttemptsRef.current += 1
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current - 1), 10000)
        reconnectTimeoutRef.current = window.setTimeout(() => {
          connectRef.current()
        }, delay)
      }
    }

    ws.onerror = () => {
      if (currentConnectionId !== connectionIdRef.current) return
      setState((prev) => ({ ...prev, connected: false }))
    }
  }, [active])

  useEffect(() => {
    connectRef.current = connect
  }, [connect])

  useEffect(() => {
    if (!active) {
      disconnect()
      return
    }

    connect()
    return disconnect
  }, [active, connect, disconnect])

  return {
    ...state,
    clearMappingCloud,
    connect,
    disconnect,
  }
}
