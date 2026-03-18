/**
 * 事件 WebSocket 连接管理。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getWsUrl } from '../config/api';
import type { AlertEvent, AIStatus, EventMessage, EventWebSocketStatus } from '../types/event';

export interface EventHookState {
  status: EventWebSocketStatus;
  alerts: AlertEvent[];
  latestAlert: AlertEvent | null;
  aiStatus: AIStatus | null;
  connect: () => void;
  disconnect: () => void;
}

export function useEventWebSocket(): EventHookState {
  const [status, setStatus] = useState<EventWebSocketStatus>({
    status: 'disconnected',
    error: null,
  });
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [latestAlert, setLatestAlert] = useState<AlertEvent | null>(null);
  const [aiStatus, setAiStatus] = useState<AIStatus | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const connectionIdRef = useRef(0);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
      wsRef.current.close();
      wsRef.current = null;
    }

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    connectionIdRef.current += 1;
    const currentConnectionId = connectionIdRef.current;

    try {
      const ws = new WebSocket(getWsUrl('/ws/event'));
      wsRef.current = ws;
      setStatus({ status: 'connecting', error: null });

      ws.onopen = () => {
        if (currentConnectionId !== connectionIdRef.current) {
          return;
        }
        setStatus({ status: 'connected', error: null });
        reconnectAttemptsRef.current = 0;
      };

      ws.onmessage = (event) => {
        if (currentConnectionId !== connectionIdRef.current) {
          return;
        }
        try {
          const message = JSON.parse(event.data) as EventMessage;

          if (message.msg_type === 'AI_STATUS' && message.payload) {
            setAiStatus(message.payload as unknown as AIStatus);
            return;
          }

          if (message.msg_type !== 'ALERT_RAISED' || !message.payload) {
            return;
          }

          const alert: AlertEvent = {
            ...message.payload,
            timestamp: message.timestamp || message.payload.timestamp,
          };

          setLatestAlert(alert);
          setAlerts((prev) => [alert, ...prev].slice(0, 10));
        } catch (error) {
          console.error('解析事件消息失败:', error);
        }
      };

      ws.onerror = () => {
        if (currentConnectionId !== connectionIdRef.current) {
          return;
        }
        setStatus({ status: 'error', error: 'WebSocket error' });
      };

      ws.onclose = (event) => {
        if (currentConnectionId !== connectionIdRef.current) {
          return;
        }
        setStatus({ status: 'disconnected', error: event.reason || null });

        if (event.code === 1000) {
          return;
        }

        if (reconnectAttemptsRef.current < 10) {
          reconnectAttemptsRef.current += 1;
          const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current - 1), 10000);
          reconnectTimeoutRef.current = window.setTimeout(() => {
            connect();
          }, delay);
        }
      };
    } catch (error) {
      console.error('创建事件 WebSocket 失败:', error);
      setStatus({ status: 'error', error: 'create failed' });
    }
  }, []);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setStatus({ status: 'disconnected', error: null });
  }, []);

  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    status,
    alerts,
    latestAlert,
    aiStatus,
    connect,
    disconnect,
  };
}
