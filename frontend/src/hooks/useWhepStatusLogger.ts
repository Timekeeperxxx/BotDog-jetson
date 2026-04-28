import { useEffect, useRef } from 'react';
import type { WhepState } from './useWhepVideo';

type AddLogFn = (message: string, level: 'info' | 'warning' | 'error', module: string) => void;

export function useWhepStatusLogger(whepStatus: WhepState, addLog: AddLogFn): void {
  const lastWhepStatusRef = useRef<string | null>(null);
  const whepDelayTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (lastWhepStatusRef.current === whepStatus.status) return;
    lastWhepStatusRef.current = whepStatus.status;
    if (whepStatus.status === 'connected') {
      if (whepDelayTimerRef.current) {
        window.clearTimeout(whepDelayTimerRef.current);
        whepDelayTimerRef.current = null;
      }
      addLog('视频流连接成功', 'info', 'WHEP');
      return;
    }
    if (whepStatus.status === 'connecting') {
      addLog('视频流连接中', 'info', 'WHEP');
      return;
    }
    if (whepDelayTimerRef.current) window.clearTimeout(whepDelayTimerRef.current);
    if (whepStatus.status === 'error') {
      addLog(`视频流连接失败: ${whepStatus.error || '未知错误'}`, 'error', 'WHEP');
      return;
    }
    if (whepStatus.status === 'disconnected') {
      whepDelayTimerRef.current = window.setTimeout(() => {
        if (whepStatus.status === 'disconnected') addLog('视频流未连接', 'warning', 'WHEP');
        whepDelayTimerRef.current = null;
      }, 3000);
    }

    return () => {
      if (whepDelayTimerRef.current) {
        window.clearTimeout(whepDelayTimerRef.current);
        whepDelayTimerRef.current = null;
      }
    };
  }, [whepStatus.status, whepStatus.error, addLog]);
}
