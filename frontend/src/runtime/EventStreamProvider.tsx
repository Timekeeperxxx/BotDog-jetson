import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { getWsUrl } from '../config/api'

export type EventStreamMessage = {
  type?: string
  event?: string
  topic?: string
  data?: unknown
  payload?: unknown
  [key: string]: unknown
}

export type EventStreamEnvelope = {
  id: number
  raw: string
  message: EventStreamMessage
  receivedAt: number
}

type EventStreamContextValue = {
  connected: boolean
  connecting: boolean
  reconnecting: boolean
  lastMessage: EventStreamMessage | null
  lastRawMessage: string | null
  lastEnvelope: EventStreamEnvelope | null
  envelopes: EventStreamEnvelope[]
  error: string | null
  connect: () => void
  disconnect: () => void
}

const fallbackContext: EventStreamContextValue = {
  connected: false,
  connecting: false,
  reconnecting: false,
  lastMessage: null,
  lastRawMessage: null,
  lastEnvelope: null,
  envelopes: [],
  error: null,
  connect: () => {},
  disconnect: () => {},
}

const EventStreamContext = createContext<EventStreamContextValue | null>(null)

export function EventStreamProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [reconnecting, setReconnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [envelopes, setEnvelopes] = useState<EventStreamEnvelope[]>([])
  const [lastRawMessage, setLastRawMessage] = useState<string | null>(null)
  const [lastMessage, setLastMessage] = useState<EventStreamMessage | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<number | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const connectionIdRef = useRef(0)
  const envelopeIdRef = useRef(0)

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimeoutRef.current !== null) {
      window.clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
  }, [])

  const disconnect = useCallback(() => {
    connectionIdRef.current += 1
    clearReconnectTimer()
    if (wsRef.current) {
      wsRef.current.close(1000)
      wsRef.current = null
    }
    setConnected(false)
    setConnecting(false)
    setReconnecting(false)
    setError(null)
  }, [clearReconnectTimer])

  const connect = useCallback(() => {
    const readyState = wsRef.current?.readyState
    if (readyState === WebSocket.OPEN || readyState === WebSocket.CONNECTING) {
      return
    }

    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
      wsRef.current.close(1000)
      wsRef.current = null
    }

    clearReconnectTimer()
    connectionIdRef.current += 1
    const currentConnectionId = connectionIdRef.current

    try {
      const ws = new WebSocket(getWsUrl('/ws/event'))
      wsRef.current = ws
      setConnecting(true)
      setReconnecting(false)
      setError(null)

      ws.onopen = () => {
        if (currentConnectionId !== connectionIdRef.current) {
          return
        }
        setConnected(true)
        setConnecting(false)
        setReconnecting(false)
        reconnectAttemptsRef.current = 0
        setError(null)
      }

      ws.onmessage = (event) => {
        if (currentConnectionId !== connectionIdRef.current) {
          return
        }

        try {
          const raw = typeof event.data === 'string' ? event.data : String(event.data)
          const message = JSON.parse(raw) as EventStreamMessage
          setError(null)
          envelopeIdRef.current += 1
          const envelope: EventStreamEnvelope = {
            id: envelopeIdRef.current,
            raw,
            message,
            receivedAt: Date.now(),
          }
          setLastRawMessage(raw)
          setLastMessage(message)
          setEnvelopes((prev) => {
            const next = [...prev, envelope]
            return next.length > 100 ? next.slice(next.length - 100) : next
          })
        } catch (parseError) {
          console.error('解析事件流消息失败:', parseError)
          setError(parseError instanceof Error ? parseError.message : '解析事件流消息失败')
        }
      }

      ws.onerror = () => {
        if (currentConnectionId !== connectionIdRef.current) {
          return
        }
        setError('WebSocket error')
      }

      ws.onclose = (event) => {
        if (currentConnectionId !== connectionIdRef.current) {
          return
        }

        setConnected(false)
        setConnecting(false)

        if (event.code === 1000) {
          setReconnecting(false)
          return
        }

        setReconnecting(true)
        if (reconnectAttemptsRef.current < 10) {
          reconnectAttemptsRef.current += 1
          const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current - 1), 10000)
          reconnectTimeoutRef.current = window.setTimeout(() => {
            connect()
          }, delay)
        }
      }
    } catch (connectError) {
      console.error('创建事件流 WebSocket 失败:', connectError)
      setConnecting(false)
      setReconnecting(false)
      setConnected(false)
      setError(connectError instanceof Error ? connectError.message : 'create failed')
    }
  }, [clearReconnectTimer])

  useEffect(() => {
    connect()
    return () => {
      disconnect()
    }
  }, [connect, disconnect])

  const value = useMemo<EventStreamContextValue>(() => ({
    connected,
    connecting,
    reconnecting,
    lastMessage,
    lastRawMessage,
    lastEnvelope: envelopes.length > 0 ? envelopes[envelopes.length - 1] : null,
    envelopes,
    error,
    connect,
    disconnect,
  }), [connected, connecting, reconnecting, lastMessage, lastRawMessage, envelopes, error, connect, disconnect])

  return <EventStreamContext.Provider value={value}>{children}</EventStreamContext.Provider>
}

export function useEventStream() {
  return useContext(EventStreamContext) ?? fallbackContext
}
