/**
 * useAutoTrack — 自动跟踪功能 Hook。
 *
 * 职责：
 * - 从 API 轮询和/或接收 WS 推送的 AutoTrackStatus
 * - 提供 enable/disable/pause/resume 控制
 * - 提供 manualOverride / releaseOverride 控制权管理
 * - 提供 markKnown / unmarkKnown 已知人员标记
 *
 * 设计：
 * - 轮询 /api/v1/auto-track/debug（2 秒间隔）作为基础状态获取
 * - WS AUTO_TRACK_STATUS 消息到来时实时更新（由 useEventWebSocket 转发）
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getApiBaseUrl } from '../config/api';
import type { AutoTrackStatus, KnownTarget } from '../types/event';

export interface TrackDecision {
  command: string;       // forward / left / right / stop
  should_send: boolean;
  reason: string;        // 人类可读决策原因
  bbox?: number[];       // [x1,y1,x2,y2]
  anchor?: number[];     // [cx, cy_bottom]
}

// API helpers
const apiPost = (path: string, body?: object) =>
  fetch(`${getApiBaseUrl()}${path}`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

const apiGet = (path: string) => fetch(`${getApiBaseUrl()}${path}`);

export interface AutoTrackHookState {
  status: AutoTrackStatus | null;
  knownTargets: KnownTarget[];
  loading: boolean;
  error: string | null;
  trackDecision: TrackDecision | null;  // 最新每帧决策
  // 控制接口
  enable: () => Promise<void>;
  disable: () => Promise<void>;
  pause: () => Promise<void>;
  resume: () => Promise<void>;
  // 仲裁接口
  manualOverride: () => Promise<void>;
  releaseOverride: () => Promise<void>;
  // 已知人员标记
  markKnown: (trackId: number) => Promise<void>;
  unmarkKnown: (trackId: number) => Promise<void>;
  fetchKnownList: () => Promise<void>;
  // 手动刷新
  refresh: () => void;
}

export function useAutoTrack(
  /** 外部推送来的 ws 消息，来自 useEventWebSocket 的 AUTO_TRACK_STATUS payload */
  wsTrackStatus?: AutoTrackStatus | null,
  /** 外部推送来的 TRACK_DECISION payload（每帧决策） */
  wsTrackDecision?: TrackDecision | null,
): AutoTrackHookState {
  const [status, setStatus] = useState<AutoTrackStatus | null>(null);
  const [knownTargets, setKnownTargets] = useState<KnownTarget[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trackDecision, setTrackDecision] = useState<TrackDecision | null>(null);
  const pollTimerRef = useRef<number | null>(null);

  // WS 推送时立即更新（最高优先级）
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
    } catch (e) {
      // 静默失败，不阻塞 UI
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

  // 首次加载 + 2 秒轮询（当 WS 可用时轮询降频也没问题）
  useEffect(() => {
    fetchStatus();
    fetchKnownList();
    pollTimerRef.current = window.setInterval(() => {
      fetchStatus();
    }, 2000);
    return () => {
      if (pollTimerRef.current !== null) {
        clearInterval(pollTimerRef.current);
      }
    };
  }, [fetchStatus, fetchKnownList]);

  // 通用控制命令工具
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
    } catch (e) {
      setError('网络错误');
    } finally {
      setLoading(false);
    }
  }, [fetchStatus]);

  const enable = useCallback(() => sendCommand('/api/v1/auto-track/enable'), [sendCommand]);
  const disable = useCallback(() => sendCommand('/api/v1/auto-track/disable'), [sendCommand]);
  const pause = useCallback(() => sendCommand('/api/v1/auto-track/pause'), [sendCommand]);
  const resume = useCallback(() => sendCommand('/api/v1/auto-track/resume'), [sendCommand]);
  const manualOverride = useCallback(() => sendCommand('/api/v1/auto-track/manual-override'), [sendCommand]);
  const releaseOverride = useCallback(() => sendCommand('/api/v1/auto-track/release-override'), [sendCommand]);

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
