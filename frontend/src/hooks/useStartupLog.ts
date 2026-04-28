import { useEffect, useRef } from 'react';

type AddLogFn = (message: string, level: 'info' | 'warning' | 'error', module: string) => void;

export function useStartupLog(addLog: AddLogFn): void {
  const startupLoggedRef = useRef(false);

  useEffect(() => {
    if (startupLoggedRef.current) return;
    startupLoggedRef.current = true;
    addLog('系统启动检查开始', 'info', 'STARTUP');
  }, [addLog]);
}
