import { useEffect, useRef } from 'react';

type ActiveTab = 'console' | 'simulate' | 'guard' | string;

interface UseVideoReconnectEffectsParams {
  activeTab: ActiveTab;
  connectWhep: () => void;
  disconnectWhep: () => void;
  connectWhep2: () => void;
  disconnectWhep2: () => void;
}

const VISIBLE_VIDEO_TABS = new Set(['console', 'simulate', 'guard']);

export function useVideoReconnectEffects({
  activeTab,
  connectWhep,
  disconnectWhep,
  connectWhep2,
  disconnectWhep2,
}: UseVideoReconnectEffectsParams): void {
  const connectWhepRef = useRef(connectWhep);
  const connectWhep2Ref = useRef(connectWhep2);

  useEffect(() => {
    connectWhepRef.current = connectWhep;
  }, [connectWhep]);

  useEffect(() => {
    connectWhep2Ref.current = connectWhep2;
  }, [connectWhep2]);

  useEffect(() => {
    if (VISIBLE_VIDEO_TABS.has(activeTab)) {
      const reconnectTimer = window.setTimeout(() => {
        connectWhepRef.current();
        connectWhep2Ref.current();
      }, 300);
      return () => window.clearTimeout(reconnectTimer);
    }
    void disconnectWhep();
    void disconnectWhep2();
  }, [activeTab, disconnectWhep, disconnectWhep2]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible' && VISIBLE_VIDEO_TABS.has(activeTab)) {
        connectWhepRef.current();
        connectWhep2Ref.current();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, [activeTab]);
}
