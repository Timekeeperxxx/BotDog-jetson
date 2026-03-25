/**
 * 机器狗控制 Hook
 *
 * 功能：
 * - 封装 POST /api/v1/control/command 调用
 * - 长按时以 100ms 间隔持续发送命令
 * - 松手 / 失焦 / 页面卸载时自动发 stop（安全底座）
 *
 * 使用方式：
 * const { startCommand, stopCommand, isControlling, lastResult } = useRobotControl();
 *
 * // 按下按钮时
 * onPointerDown={() => startCommand('forward')}
 * // 松手时
 * onPointerUp={stopCommand}
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getApiUrl } from '../config/api';

// 支持的动作名
export type RobotCommand =
  | 'forward'
  | 'backward'
  | 'left'
  | 'right'
  | 'sit'
  | 'stand'
  | 'stop';

// 后端响应
export interface ControlAck {
  ack_cmd: string;
  result: 'ACCEPTED' | 'REJECTED_E_STOP' | 'REJECTED_INVALID_CMD' | 'RATE_LIMITED';
  latency_ms: number;
}

// 命令发送间隔（ms）
const SEND_INTERVAL_MS = 500;

// 控制 API URL
const CONTROL_URL = getApiUrl('/api/v1/control/command');
const STOP_URL = getApiUrl('/api/v1/control/stop');

export interface UseRobotControlReturn {
  /** 开始持续发送命令（长按时调用） */
  startCommand: (cmd: RobotCommand) => void;
  /** 停止发送，立即发 stop（松手时调用） */
  stopCommand: () => void;
  /** 当前是否正在控制中 */
  isControlling: boolean;
  /** 上一次命令结果 */
  lastResult: ControlAck | null;
  /** 当前正在执行的命令 */
  currentCmd: RobotCommand | null;
}

export function useRobotControl(): UseRobotControlReturn {
  const [isControlling, setIsControlling] = useState(false);
  const [lastResult, setLastResult] = useState<ControlAck | null>(null);
  const [currentCmd, setCurrentCmd] = useState<RobotCommand | null>(null);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isSendingRef = useRef(false); // 防止并发发送

  // ── 发送单次命令 ──────────────────────────────────────────────────────────

  const sendCommand = useCallback(async (cmd: RobotCommand | 'stop') => {
    if (isSendingRef.current) return;
    isSendingRef.current = true;

    try {
      const url = cmd === 'stop' ? STOP_URL : CONTROL_URL;
      const body = cmd === 'stop' ? undefined : JSON.stringify({ cmd });

      const res = await fetch(url, {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body,
        // 短超时，防止请求积压
        signal: AbortSignal.timeout(1000),
      });

      if (res.ok) {
        const ack: ControlAck = await res.json();
        setLastResult(ack);
      }
    } catch {
      // 网络错误静默忽略（Watchdog 会超时保底）
    } finally {
      isSendingRef.current = false;
    }
  }, []);

  // ── 清理 interval ──────────────────────────────────────────────────────────

  const clearInterval_ = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  // ── startCommand：长按开始持续发送 ────────────────────────────────────────

  const startCommand = useCallback((cmd: RobotCommand) => {
    // 清理旧 interval（防止重复触发）
    clearInterval_();

    setIsControlling(true);
    setCurrentCmd(cmd);

    // 立即发一次
    sendCommand(cmd);

    // 持续发送
    intervalRef.current = setInterval(() => {
      sendCommand(cmd);
    }, SEND_INTERVAL_MS);
  }, [sendCommand, clearInterval_]);

  // ── stopCommand：松手立即 stop ────────────────────────────────────────────

  const stopCommand = useCallback(() => {
    clearInterval_();
    setIsControlling(false);
    setCurrentCmd(null);
    sendCommand('stop');
  }, [sendCommand, clearInterval_]);

  // ── 安全底座：失焦 / 页面卸载时自动 stop ─────────────────────────────────

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.hidden) {
        stopCommand();
      }
    };

    const handleBeforeUnload = () => {
      // 使用 sendBeacon 保证页面卸载时能发出请求
      navigator.sendBeacon(STOP_URL);
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('beforeunload', handleBeforeUnload);
      // 组件卸载时停止
      clearInterval_();
      sendCommand('stop');
    };
  }, [stopCommand, sendCommand, clearInterval_]);

  return {
    startCommand,
    stopCommand,
    isControlling,
    lastResult,
    currentCmd,
  };
}
