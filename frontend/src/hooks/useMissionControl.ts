import { useCallback, useEffect, useRef, useState } from 'react';
import { getApiUrl } from '../config/api';

export interface UseMissionControlState {
  missionTaskId: number | null;
  isMissionRunning: boolean;
  toggleMission: () => Promise<void>;
}

export function useMissionControl(addLog: (message: string, level: 'info' | 'warning' | 'error', module: string) => void): UseMissionControlState {
  const [missionTaskId, setMissionTaskId] = useState<number | null>(null);
  const busy = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch(getApiUrl('/api/v1/session/current'), { signal: controller.signal })
      .then(async res => {
        if (!res.ok) throw new Error(`读取巡检状态失败 (${res.status})`);
        const task = await res.json();
        if (!controller.signal.aborted) setMissionTaskId(task?.task_id ?? null);
      })
      .catch(err => {
        if (!controller.signal.aborted) addLog(`任务状态同步失败: ${err}`, 'error', 'MISSION');
      });
    return () => controller.abort();
  }, [missionTaskId, addLog]);

  const toggleMission = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      const currentRes = await fetch(getApiUrl('/api/v1/session/current'));
      if (!currentRes.ok) throw new Error(`读取巡检状态失败 (${currentRes.status})`);
      const currentTask = await currentRes.json();
      if (currentTask) {
        await fetch(getApiUrl('/api/v1/auto-track/disable'), { method: 'POST' })
          .catch(err => console.error('停用跟踪失败', err));
        const res = await fetch(getApiUrl('/api/v1/session/stop'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_id: currentTask.task_id }),
        });
        if (!res.ok) throw new Error(`停止巡检失败 (${res.status})`);
        setMissionTaskId(null);
        addLog('任务已停止，AI 跟踪已禁用', 'info', 'MISSION');
      } else {
        await fetch(getApiUrl('/api/v1/auto-track/disable'), { method: 'POST' })
          .catch(err => console.error('停用跟踪失败', err));
        const res = await fetch(getApiUrl('/api/v1/session/start'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_name: `巡检_${new Date().toLocaleTimeString([], { hour12: false })}` }),
        });
        if (!res.ok) throw new Error(`启动巡检失败 (${res.status})`);
        const data = await res.json();
        setMissionTaskId(data.task_id);
        addLog(`任务已启动: ${data.task_name}，AI 跟踪已禁用`, 'info', 'MISSION');
      }
    } catch (err) {
      addLog(`任务操作失败: ${err}`, 'error', 'MISSION');
    } finally {
      busy.current = false;
    }
  }, [addLog]);

  return {
    missionTaskId,
    isMissionRunning: missionTaskId !== null,
    toggleMission,
  };
}
