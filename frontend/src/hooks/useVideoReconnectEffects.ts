import { useEffect, useRef } from 'react';

type ActiveTab = 'console' | 'simulate' | 'guard' | string;

interface UseVideoReconnectEffectsParams {
  activeTab: ActiveTab;
  connectWhep: () => void;
  disconnectWhep: () => void;
}

const VISIBLE_VIDEO_TABS = new Set(['console', 'simulate', 'guard']);

export function useVideoReconnectEffects({
  activeTab,
  connectWhep,
  disconnectWhep,
}: UseVideoReconnectEffectsParams): void {
  const connectWhepRef = useRef(connectWhep);

  useEffect(() => {
    connectWhepRef.current = connectWhep;
  }, [connectWhep]);

  useEffect(() => {
    if (VISIBLE_VIDEO_TABS.has(activeTab)) {
      const reconnectTimer = window.setTimeout(() => {
        connectWhepRef.current();
      }, 300);
      return () => window.clearTimeout(reconnectTimer);
    }
    void disconnectWhep();
  }, [activeTab, disconnectWhep]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible' && VISIBLE_VIDEO_TABS.has(activeTab)) {
        connectWhepRef.current();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, [activeTab]);
}
