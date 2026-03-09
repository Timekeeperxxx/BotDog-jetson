/**
 * 控制 WebSocket 连接管理 Hook。
 *
 * 职责边界：
 * - 管理 /ws/control 连接
 * - 发送 MANUAL_CONTROL 指令
 * - 接收 CONTROL_ACK 确认
 * - 处理连接状态
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { ControlAck, ManualControl } from "../types/telemetry";
import { getWsUrl } from "../config/api";

/**
 * WebSocket 连接状态
 */
export type ControlConnectionStatus = "connecting" | "connected" | "disconnected" | "error";

/**
 * Hook 返回值
 */
export interface UseControlWebSocketReturn {
  status: ControlConnectionStatus;
  error: string | null;
  lastAck: ControlAck | null;
  sendControl: (control: ManualControl) => boolean;
  reconnect: () => void;
  isRateLimited: boolean;
}

/**
 * 控制 WebSocket Hook
 *
 * @param wsUrl WebSocket 地址
 * @returns 连接状态和控制方法
 */
export function useControlWebSocket(
  wsUrl?: string
): UseControlWebSocketReturn {
  const [status, setStatus] = useState<ControlConnectionStatus>("disconnected");
  const [error, setError] = useState<string | null>(null);
  const [lastAck, setLastAck] = useState<ControlAck | null>(null);
  const [isRateLimited, setIsRateLimited] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const rateLimitTimeoutRef = useRef<number | null>(null);

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

    if (rateLimitTimeoutRef.current) {
      window.clearTimeout(rateLimitTimeoutRef.current);
      rateLimitTimeoutRef.current = null;
    }
  }, []);

  /**
   * 建立 WebSocket 连接
   */
  const connect = useCallback(() => {
    try {
      setStatus("connecting");
      setError(null);

      const url = wsUrl || getWsUrl('/ws/control');
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("connected");
        setError(null);
        reconnectAttemptsRef.current = 0;
        console.log("控制 WebSocket 连接已建立");
      };

      ws.onmessage = (event) => {
        try {
          const parsedMessage = JSON.parse(event.data);

          // 处理 CONTROL_ACK 消息
          if (parsedMessage.msg_type === "CONTROL_ACK" && parsedMessage.payload) {
            const ack = parsedMessage.payload as ControlAck;
            setLastAck(ack);

            // 处理限流状态
            if (ack.result === "RATE_LIMITED") {
              setIsRateLimited(true);

              // 500ms 后重置限流状态
              if (rateLimitTimeoutRef.current) {
                window.clearTimeout(rateLimitTimeoutRef.current);
              }
              rateLimitTimeoutRef.current = window.setTimeout(() => {
                setIsRateLimited(false);
              }, 500);
            }
          }
        } catch (parseError) {
          console.error("解析控制 WebSocket 消息失败:", parseError);
        }
      };

      ws.onclose = (event) => {
        console.log(`控制 WebSocket 连接关闭: code=${event.code}, reason=${event.reason}`);

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
            `控制 WebSocket 将在 ${delay}ms 后重连（第 ${reconnectAttemptsRef.current} 次）`
          );

          reconnectTimeoutRef.current = window.setTimeout(() => {
            connect();
          }, delay);
        } else if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
          setError("控制 WebSocket 重连次数已达上限");
          setStatus("error");
        }
      };

      ws.onerror = () => {
        setStatus("error");
        setError("控制 WebSocket 连接错误");
      };
    } catch (connectError) {
      setStatus("error");
      setError(`连接失败: ${connectError}`);
    }
  }, [wsUrl]);

  /**
   * 发送控制指令
   */
  const sendControl = useCallback(
    (control: ManualControl): boolean => {
      const ws = wsRef.current;

      if (!ws || ws.readyState !== WebSocket.OPEN) {
        setError("控制 WebSocket 未连接");
        return false;
      }

      try {
        ws.send(JSON.stringify(control));
        return true;
      } catch (sendError) {
        console.error("发送控制指令失败:", sendError);
        setError(`发送控制指令失败: ${sendError}`);
        return false;
      }
    },
    []
  );

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
    status,
    error,
    lastAck,
    sendControl,
    reconnect,
    isRateLimited,
  };
}
