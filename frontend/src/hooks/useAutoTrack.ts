/**
 * useAutoTrack — 自动跟踪功能 Hook。
 *
 * 逻辑：
 * - 轮询 /api/v1/auto-track/debug（2 秒间隔）+ WS 推送实时更新
 * - 当状态变为 PAUSED / MANUAL_OVERRIDE（手动接管），启动 5 秒倒计时，
 *   若期间无手动操作则自动调用 resume()
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getApiBaseUrl } from '../config/api';
import type { AutoTrackStatus, KnownTarget } from '../types/event';

export interface TrackDecision {
  command: string;
  should_send: boolean;
  reason: string;
  bbox?: number[];
  anchor?: number[];
  track_id?: number;
}

const apiPost = (path: string, body?: object) =>
  fetch(`${getApiBaseUrl()}${path}`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

const apiGet = (path: string) => fetch(`${getApiBaseUrl()}${path}`);

// 手动接管后多少毫秒自动恢复跟踪
const AUTO_RESUME_MS = 5000;

export interface AutoTrackHookState {
  status: AutoTrackStatus | null;
  knownTargets: KnownTarget[];
  loading: boolean;
  error: string | null;
  trackDecision: TrackDecision | null;
  enable: () => Promise<void>;
  disable: () => Promise<void>;
  pause: () => Promise<void>;
  resume: () => Promise<void>;
  manualOverride: () => Promise<void>;
  releaseOverride: () => Promise<void>;
  markKnown: (trackId: number) => Promise<void>;
  unmarkKnown: (trackId: number) => Promise<void>;
  fetchKnownList: () => Promise<void>;
  refresh: () => void;
}

export function useAutoTrack(
  wsTrackStatus?: AutoTrackStatus | null,
  wsTrackDecision?: TrackDecision | null,
): AutoTrackHookState {
  const [status, setStatus] = useState<AutoTrackStatus | null>(null);
  const [knownTargets, setKnownTargets] = useState<KnownTarget[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trackDecision, setTrackDecision] = useState<TrackDecision | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  const autoResumeTimerRef = useRef<number | null>(null);

  // WS 推送时立即更新
  useEffect(() => {
    if (wsTrackStatus) setStatus(wsTrackStatus);
  }, [wsTrackStatus]);

  useEffect(() => {
    if (wsTrackDecision) setTrackDecision(wsTrackDecision);
  }, [wsTrackDecision]);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await apiGet('/api/v1/auto-track/debug');
      if (!res.ok) return;
      const data = await res.json() as AutoTrackStatus;
      setStatus(data);
      setError(null);
    } catch {
      setError('无法获取跟踪状态');
    }
  }, []);

  const fetchKnownList = useCallback(async () => {
    try {
      const res = await apiGet('/api/v1/auto-track/known-list');
      if (!res.ok) return;
      const data = await res.json() as { known_ids: number[]; total: number };
      setKnownTargets(data.known_ids.map(id => ({ track_id: id })));
    } catch {
      // 静默失败
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    fetchKnownList();
    pollTimerRef.current = window.setInterval(fetchStatus, 2000);
    return () => {
      if (pollTimerRef.current !== null) clearInterval(pollTimerRef.current);
    };
  }, [fetchStatus, fetchKnownList]);

  const sendCommand = useCallback(async (path: string) => {
    setLoading(true);
    try {
      const res = await apiPost(path);
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        setError(body.detail || '命令失败');
      } else {
        setError(null);
        await fetchStatus();
      }
    } catch {
      setError('网络错误');
    } finally {
      setLoading(false);
    }
  }, [fetchStatus]);

  const enable  = useCallback(() => sendCommand('/api/v1/auto-track/enable'),  [sendCommand]);
  const disable = useCallback(() => sendCommand('/api/v1/auto-track/disable'), [sendCommand]);
  const pause   = useCallback(() => sendCommand('/api/v1/auto-track/pause'),   [sendCommand]);
  const resume  = useCallback(() => sendCommand('/api/v1/auto-track/resume'),  [sendCommand]);
  const manualOverride  = useCallback(() => sendCommand('/api/v1/auto-track/manual-override'),  [sendCommand]);
  const releaseOverride = useCallback(() => sendCommand('/api/v1/auto-track/release-override'), [sendCommand]);

  // ── 手动接管后自动恢复 ────────────────────────────────────────────────────
  // 检测到 PAUSED / MANUAL_OVERRIDE 后启动 AUTO_RESUME_MS 倒计时。
  // resume() 调用后进入 RESUME_COOLDOWN_MS 冷却，防止后端持续返回 PAUSED 时无限循环。
  const prevStateRef = useRef<string | null>(null);
  const lastResumeAtRef = useRef<number>(0);
  const RESUME_COOLDOWN_MS = 10_000; // resume 后 10 秒内不再自动触发

  useEffect(() => {
    const currentState = status?.state ?? null;
    const isPaused = currentState === 'PAUSED' || currentState === 'MANUAL_OVERRIDE';

    if (isPaused) {
      // 冷却期内不重新计时
      if (Date.now() - lastResumeAtRef.current < RESUME_COOLDOWN_MS) return;

      if (autoResumeTimerRef.current !== null) clearTimeout(autoResumeTimerRef.current);
      autoResumeTimerRef.current = window.setTimeout(() => {
        autoResumeTimerRef.current = null;
        lastResumeAtRef.current = Date.now();
        void resume();
      }, AUTO_RESUME_MS);
    } else {
      if (autoResumeTimerRef.current !== null) {
        clearTimeout(autoResumeTimerRef.current);
        autoResumeTimerRef.current = null;
      }
    }

    prevStateRef.current = currentState;
  }, [status?.state, resume]);


  // 组件卸载时清理
  useEffect(() => {
    return () => {
      if (autoResumeTimerRef.current !== null) clearTimeout(autoResumeTimerRef.current);
    };
  }, []);

  const markKnown = useCallback(async (trackId: number) => {
    await sendCommand(`/api/v1/auto-track/mark-known/${trackId}`);
    await fetchKnownList();
  }, [sendCommand, fetchKnownList]);

  const unmarkKnown = useCallback(async (trackId: number) => {
    await sendCommand(`/api/v1/auto-track/unmark-known/${trackId}`);
    await fetchKnownList();
  }, [sendCommand, fetchKnownList]);

  return {
    status,
    knownTargets,
    loading,
    error,
    trackDecision,
    enable,
    disable,
    pause,
    resume,
    manualOverride,
    releaseOverride,
    markKnown,
    unmarkKnown,
    fetchKnownList,
    refresh: fetchStatus,
  };
}
