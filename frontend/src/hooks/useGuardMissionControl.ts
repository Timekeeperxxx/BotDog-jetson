import { useCallback, useEffect, useState } from 'react';
import { getApiUrl } from '../config/api';
import type { GuardStatus } from '../components/GuardControlCenter';

export interface UseGuardMissionControlState {
  guardStatus: GuardStatus | null;
  toggleGuardMission: () => Promise<void>;
  abortGuardMission: () => Promise<void>;
}

export function useGuardMissionControl(): UseGuardMissionControlState {
  const [guardStatus, setGuardStatus] = useState<GuardStatus | null>(null);

  useEffect(() => {
    const fetchGuardStatus = async () => {
      try {
        const res = await fetch(getApiUrl('/api/v1/guard-mission/status'));
        if (res.ok) setGuardStatus(await res.json());
      } catch {}
    };
    fetchGuardStatus();
    const timer = setInterval(fetchGuardStatus, 1500);
    return () => clearInterval(timer);
  }, []);

  const toggleGuardMission = useCallback(async () => {
    try {
      const endpoint = guardStatus?.enabled ? '/disable' : '/enable';
      await fetch(getApiUrl(`/api/v1/guard-mission${endpoint}`), { method: 'POST' });
    } catch (err) {
      console.error('切换自动驱离失败:', err);
    }
  }, [guardStatus?.enabled]);

  const abortGuardMission = useCallback(async () => {
    try {
      await fetch(getApiUrl('/api/v1/guard-mission/abort'), { method: 'POST' });
    } catch (err) {
      console.error('中止驱离失败:', err);
    }
  }, []);

  return {
    guardStatus,
    toggleGuardMission,
    abortGuardMission,
  };
}
