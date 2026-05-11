/**
 * 事件 WebSocket 连接管理。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useEventStream } from '../runtime/EventStreamProvider'
import type { AlertEvent, AIStatus, EventWebSocketStatus, AutoTrackStatus } from '../types/event'
import type { TrackDecision } from './useAutoTrack'
import type { TrackOverlayData } from '../components/TrackOverlay1'

export interface EventHookState {
  status: EventWebSocketStatus
  alerts: AlertEvent[]
  latestAlert: AlertEvent | null
  aiStatus: AIStatus | null
  autoTrackStatus: AutoTrackStatus | null
  trackDecision: TrackDecision | null
  trackOverlay: TrackOverlayData | null
  connect: () => void
  disconnect: () => void
}

export function useEventWebSocket(): EventHookState {
  const stream = useEventStream()
  const [alerts, setAlerts] = useState<AlertEvent[]>([])
  const [latestAlert, setLatestAlert] = useState<AlertEvent | null>(null)
  const [aiStatus, setAiStatus] = useState<AIStatus | null>(null)
  const [autoTrackStatus, setAutoTrackStatus] = useState<AutoTrackStatus | null>(null)
  const [trackDecision, setTrackDecision] = useState<TrackDecision | null>(null)
  const [trackOverlay, setTrackOverlay] = useState<TrackOverlayData | null>(null)
  const processedEnvelopeIdRef = useRef(0)
  const initializedRef = useRef(false)

  const status = useMemo<EventWebSocketStatus>(() => {
    if (stream.error) {
      return {
        status: 'error',
        error: stream.error,
      }
    }

    if (stream.connected) {
      return { status: 'connected', error: null }
    }

    if (stream.connecting || stream.reconnecting) {
      return { status: 'connecting', error: null }
    }

    return { status: 'disconnected', error: null }
  }, [stream.connected, stream.connecting, stream.error, stream.reconnecting])

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
      const message = envelope.message as { msg_type?: string; timestamp?: string; payload?: Record<string, any> }
      if (!message?.msg_type) {
        return
      }

      if (message.msg_type === 'AI_STATUS' && message.payload) {
        setAiStatus(message.payload as unknown as AIStatus)
        return
      }

      if (message.msg_type === 'AUTO_TRACK_STATUS' && message.payload) {
        setAutoTrackStatus(message.payload as unknown as AutoTrackStatus)
        return
      }

      if (message.msg_type === 'TRACK_DECISION' && message.payload) {
        setTrackDecision(message.payload as unknown as TrackDecision)
        return
      }

      if (message.msg_type === 'TRACK_OVERLAY' && message.payload) {
        setTrackOverlay(message.payload as unknown as TrackOverlayData)
        return
      }

      if (
        ![
          'ALERT_RAISED',
          'STRANGER_TARGET_LOCKED',
          'AUTO_TRACK_STARTED',
          'AUTO_TRACK_STOPPED',
          'AUTO_TRACK_MANUAL_OVERRIDE',
        ].includes(message.msg_type) || !message.payload
      ) {
        return
      }

      const alert: AlertEvent = {
        ...(message.payload as any),
        timestamp: message.timestamp || (message.payload as any).timestamp,
      }

      setLatestAlert(alert)
      setAlerts((prev) => [alert, ...prev].slice(0, 10))
    })

    processedEnvelopeIdRef.current = pending[pending.length - 1].id
  }, [stream.envelopes])

  const connect = useCallback(() => {
    stream.connect()
  }, [stream.connect])

  const disconnect = useCallback(() => {
    stream.disconnect()
  }, [stream.disconnect])

  return {
    status,
    alerts,
    latestAlert,
    aiStatus,
    autoTrackStatus,
    trackDecision,
    trackOverlay,
    connect,
    disconnect,
  }
}
