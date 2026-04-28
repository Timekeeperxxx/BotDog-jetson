import { useEffect, useRef } from 'react';

type AddLogFn = (message: string, level: 'info' | 'warning' | 'error', module: string) => void;

export function useWebSocketStatusLogger(isConnected: boolean, addLog: AddLogFn): void {
  const lastWsStatusRef = useRef<boolean | null>(null);
  const wsDelayTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (lastWsStatusRef.current === isConnected) return;
    lastWsStatusRef.current = isConnected;
    if (isConnected) {
      if (wsDelayTimerRef.current) {
        window.clearTimeout(wsDelayTimerRef.current);
        wsDelayTimerRef.current = null;
      }
      addLog('遥测链路已连接', 'info', 'WS');
      return;
    }
    if (wsDelayTimerRef.current) window.clearTimeout(wsDelayTimerRef.current);
    wsDelayTimerRef.current = window.setTimeout(() => {
      if (!isConnected) addLog('遥测链路未连接', 'error', 'WS');
      wsDelayTimerRef.current = null;
    }, 3000);

    return () => {
      if (wsDelayTimerRef.current) {
        window.clearTimeout(wsDelayTimerRef.current);
        wsDelayTimerRef.current = null;
      }
    };
  }, [isConnected, addLog]);
}
