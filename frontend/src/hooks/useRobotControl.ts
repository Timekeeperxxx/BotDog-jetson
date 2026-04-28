/**
 * 机器狗控制 Hook
 *
 * 功能：
 * - 封装 POST /api/v1/control/command 调用
 * - 长按时以 500ms 间隔持续发送命令
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
  | 'strafe_left'
  | 'strafe_right'
  | 'sit'
  | 'stand'
  | 'stop';

// 后端结果码
export type ControlResult =
  | 'ACCEPTED'
  | 'REJECTED_E_STOP'
  | 'REJECTED_INVALID_CMD'
  | 'RATE_LIMITED'
  | 'REJECTED_ADAPTER_NOT_READY'
  | 'REJECTED_ADAPTER_ERROR';

// 后端响应
export interface ControlAck {
  ack_cmd: string;
  result: ControlResult;
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
  /** 命令结果对应的中文提示 */
  resultMessage: string | null;
}

export function useRobotControl(): UseRobotControlReturn {
  const [isControlling, setIsControlling] = useState(false);
  const [lastResult, setLastResult] = useState<ControlAck | null>(null);
  const [currentCmd, setCurrentCmd] = useState<RobotCommand | null>(null);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // 普通运动命令的发送锁：防止 forward/backward/... 请求在上一个未完成时堆积
  const normalSendingRef = useRef(false);
  // stop 命令的独立发送锁：只防止 stop 自身并发，与 normalSendingRef 完全隔离
  const stopSendingRef = useRef(false);

  // 根据结果码获取中文提示
  const getResultMessage = (result: ControlResult): string | null => {
    switch (result) {
      case 'ACCEPTED':
        return null;
      case 'REJECTED_ADAPTER_NOT_READY':
        return '机器人控制适配器未就绪';
      case 'REJECTED_ADAPTER_ERROR':
        return '机器人控制命令发送失败';
      case 'REJECTED_E_STOP':
        return '急停状态，控制命令已拒绝';
      case 'REJECTED_INVALID_CMD':
        return '非法控制命令';
      case 'RATE_LIMITED':
        return '命令过快';
      default:
        return null;
    }
  };

  const resultMessage = lastResult ? getResultMessage(lastResult.result) : null;

  // ── 清理 interval ──────────────────────────────────────────────────────────

  const clearInterval_ = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  // ── 发送普通运动命令（受 normalSendingRef 保护，防止请求堆积）──────────────

  const sendNormalCommand = useCallback(async (cmd: RobotCommand) => {
    if (normalSendingRef.current) return;
    normalSendingRef.current = true;

    try {
      const res = await fetch(CONTROL_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cmd }),
        signal: AbortSignal.timeout(1000),
      });

      if (res.ok) {
        const ack: ControlAck = await res.json();
        setLastResult(ack);
      } else {
        setLastResult({ ack_cmd: cmd, result: 'REJECTED_ADAPTER_ERROR', latency_ms: 0 });
      }
    } catch {
      setLastResult({ ack_cmd: cmd, result: 'REJECTED_ADAPTER_ERROR', latency_ms: 0 });
    } finally {
      normalSendingRef.current = false;
    }
  }, []);

  // ── 发送 stop 命令（独立锁，绝不被 normalSendingRef 阻塞）────────────────

  const sendStopCommand = useCallback(async () => {
    if (stopSendingRef.current) return;
    stopSendingRef.current = true;

    try {
      const res = await fetch(STOP_URL, {
        method: 'POST',
        signal: AbortSignal.timeout(1000),
      });

      if (res.ok) {
        const ack: ControlAck = await res.json();
        setLastResult(ack);
      } else {
        setLastResult({ ack_cmd: 'stop', result: 'REJECTED_ADAPTER_ERROR', latency_ms: 0 });
      }
    } catch {
      setLastResult({ ack_cmd: 'stop', result: 'REJECTED_ADAPTER_ERROR', latency_ms: 0 });
    } finally {
      stopSendingRef.current = false;
    }
  }, []);

  // ── startCommand：长按开始持续发送 ────────────────────────────────────────

  const startCommand = useCallback((cmd: RobotCommand) => {
    clearInterval_();

    setIsControlling(true);
    setCurrentCmd(cmd);

    sendNormalCommand(cmd);

    intervalRef.current = setInterval(() => {
      sendNormalCommand(cmd);
    }, SEND_INTERVAL_MS);
  }, [sendNormalCommand, clearInterval_]);

  // ── stopCommand：松手立即 stop（interval 同步清理，stop 不受普通命令锁影响）

  const stopCommand = useCallback(() => {
    clearInterval_();
    setIsControlling(false);
    setCurrentCmd(null);
    sendStopCommand();
  }, [sendStopCommand, clearInterval_]);

  // ── 安全底座：失焦 / 页面卸载 / 组件卸载时自动 stop ──────────────────────

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.hidden) {
        stopCommand();
      }
    };

    const handleBeforeUnload = () => {
      // sendBeacon 保证页面卸载时请求能发出
      navigator.sendBeacon(STOP_URL);
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('beforeunload', handleBeforeUnload);
      clearInterval_();
      sendStopCommand();
    };
  }, [stopCommand, sendStopCommand, clearInterval_]);

  return {
    startCommand,
    stopCommand,
    isControlling,
    lastResult,
    currentCmd,
    resultMessage,
  };
}
