/**
 * 事件 WebSocket Hook - 用于接收实时告警和通知
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { AlertEvent, EventMessage, EventWebSocketStatus } from '../types/event';
import { getWsUrl } from '../config/api';

export function useEventWebSocket() {
  const [status, setStatus] = useState<EventWebSocketStatus>({
    status: 'disconnected',
    error: null,
  });

  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const connectAttemptRef = useRef(0);

  const connect = useCallback(() => {
    try {
      // 防止重复连接
      if (status.status === 'connecting' || status.status === 'connected') {
        console.log('事件 WebSocket 正在连接或已连接，跳过重复连接');
        return;
      }

      // 限制重连频率
      const now = Date.now();
      if (now - connectAttemptRef.current < 5000) {
        console.log('事件 WebSocket 重连太频繁，5秒后再试');
        return;
      }
      connectAttemptRef.current = now;

      setStatus({ status: 'connecting', error: null });

      // 连接到事件 WebSocket
      const ws = new WebSocket(getWsUrl('/ws/event'));
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('事件 WebSocket 连接已建立');
        setStatus({ status: 'connected', error: null });
      };

      ws.onmessage = (event) => {
        try {
          const message: EventMessage = JSON.parse(event.data);
          console.log('收到事件消息:', message.msg_type);

          if (message.msg_type === 'ALERT_RAISED') {
            const alert = message.payload;
            console.log('收到告警:', alert);

            // 添加到告警列表
            setAlerts((prev) => [alert, ...prev].slice(0, 100)); // 最多保留 100 条

            // 可以在这里添加通知提示
            if (alert.severity === 'CRITICAL') {
              // 严重告警，显示通知
              console.warn('严重告警:', alert.message);
            }
          }
        } catch (error) {
          console.error('解析事件消息失败:', error);
        }
      };

      ws.onerror = (error) => {
        console.error('事件 WebSocket 错误:', error);
        setStatus({ status: 'error', error: '连接错误' });
      };

      ws.onclose = () => {
        console.log('事件 WebSocket 连接已关闭');
        setStatus({ status: 'disconnected', error: null });

        // 自动重连（5秒后）
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }
        reconnectTimeoutRef.current = setTimeout(() => {
          console.log('尝试重新连接事件 WebSocket...');
          connect();
        }, 5000);
      };
    } catch (error) {
      console.error('连接事件 WebSocket 失败:', error);
      setStatus({ status: 'error', error: String(error) });
    }
  }, [status.status]);

  const disconnect = () => {
    console.log('断开事件 WebSocket 连接...');
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setStatus({ status: 'disconnected', error: null });
  };

  const clearAlerts = () => {
    setAlerts([]);
  };

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, []);

  return {
    status,
    alerts,
    connect,
    disconnect,
    clearAlerts,
  };
}
