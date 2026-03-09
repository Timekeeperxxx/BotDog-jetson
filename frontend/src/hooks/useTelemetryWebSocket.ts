/**
 * WebSocket 连接管理 Hook。
 *
 * 职责边界：
 * - 管理 WebSocket 连接生命周期
 * - 处理自动重连逻辑
 * - 解析并分发遥测消息
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { TelemetryMessage } from "../types/telemetry";
import { getWsUrl } from "../config/api";

/**
 * WebSocket 连接状态
 */
export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "error";

/**
 * Hook 返回值
 */
export interface UseTelemetryWebSocketReturn {
  message: TelemetryMessage | null;
  status: ConnectionStatus;
  error: string | null;
  reconnect: () => void;
}

/**
 * 遥测 WebSocket Hook
 *
 * @param wsUrl WebSocket 地址
 * @returns 连接状态和最新消息
 */
export function useTelemetryWebSocket(
  wsUrl?: string
): UseTelemetryWebSocketReturn {
  const [message, setMessage] = useState<TelemetryMessage | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);

  /**
   * 最大重连次数
   */
  const MAX_RECONNECT_ATTEMPTS = 10;

  /**
   * 基础重连延迟（毫秒）
   */
  const BASE_RECONNECT_DELAY = 1000;

  /**
   * 清理 WebSocket 连接
   */
  const cleanup = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    if (reconnectTimeoutRef.current) {
      window.clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  /**
   * 建立 WebSocket 连接
   */
  const connect = useCallback(() => {
    try {
      setStatus("connecting");
      setError(null);

      const url = wsUrl || getWsUrl('/ws/telemetry');
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("connected");
        setError(null);
        reconnectAttemptsRef.current = 0;
        console.log("WebSocket 连接已建立");
      };

      ws.onmessage = (event) => {
        try {
          const parsedMessage = JSON.parse(event.data) as TelemetryMessage;

          // 验证消息类型
          if (parsedMessage.msg_type === "TELEMETRY_UPDATE") {
            setMessage(parsedMessage);
          }
        } catch (parseError) {
          console.error("解析 WebSocket 消息失败:", parseError);
        }
      };

      ws.onclose = (event) => {
        console.log(`WebSocket 连接关闭: code=${event.code}, reason=${event.reason}`);

        setStatus("disconnected");

        // 非主动关闭时尝试重连
        if (event.code !== 1000 && reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current += 1;

          // 指数退避重连
          const delay = Math.min(
            BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttemptsRef.current - 1),
            30000
          );

          console.log(
            `WebSocket 将在 ${delay}ms 后重连（第 ${reconnectAttemptsRef.current} 次）`
          );

          reconnectTimeoutRef.current = window.setTimeout(() => {
            connect();
          }, delay);
        } else if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
          setError("WebSocket 重连次数已达上限");
          setStatus("error");
        }
      };

      ws.onerror = () => {
        setStatus("error");
        setError("WebSocket 连接错误");
      };
    } catch (connectError) {
      setStatus("error");
      setError(`连接失败: ${connectError}`);
    }
  }, [wsUrl]);

  /**
   * 手动重连
   */
  const reconnect = useCallback(() => {
    cleanup();
    reconnectAttemptsRef.current = 0;
    connect();
  }, [cleanup, connect]);

  /**
   * 组件挂载时建立连接，卸载时清理
   */
  useEffect(() => {
    connect();

    return () => {
      cleanup();
    };
  }, [connect, cleanup]);

  return {
    message,
    status,
    error,
    reconnect,
  };
}
