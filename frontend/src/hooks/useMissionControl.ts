import { useCallback, useState } from 'react';
import { getApiUrl } from '../config/api';

export interface UseMissionControlState {
  missionTaskId: number | null;
  isMissionRunning: boolean;
  toggleMission: () => Promise<void>;
}

export function useMissionControl(addLog: (message: string, level: 'info' | 'warning' | 'error', module: string) => void): UseMissionControlState {
  const [missionTaskId, setMissionTaskId] = useState<number | null>(null);

  const toggleMission = useCallback(async () => {
    try {
      if (missionTaskId) {
        await fetch(getApiUrl('/api/v1/auto-track/disable'), { method: 'POST' })
          .catch(err => console.error('停用跟踪失败', err));
        await fetch(getApiUrl('/api/v1/session/stop'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_id: missionTaskId }),
        });
        setMissionTaskId(null);
        addLog('任务已停止，AI 跟踪已禁用', 'info', 'MISSION');
      } else {
        const res = await fetch(getApiUrl('/api/v1/session/start'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_name: `巡检_${new Date().toLocaleTimeString([], { hour12: false })}` }),
        });
        const data = await res.json();
        setMissionTaskId(data.task_id);
        addLog(`任务已启动: ${data.task_name}`, 'info', 'MISSION');
      }
    } catch (err) {
      addLog(`任务操作失败: ${err}`, 'error', 'MISSION');
    }
  }, [missionTaskId, addLog]);

  return {
    missionTaskId,
    isMissionRunning: missionTaskId !== null,
    toggleMission,
  };
}
