/**
 * 视频源 & 网口管理 Hook
 *
 * 提供视频源和网口配置的 CRUD 操作
 */

import { useState, useCallback } from 'react';
import type { VideoSource, VideoSourceRequest, NetworkInterface, NetworkInterfaceRequest } from '../types/admin';
import { getApiUrl } from '../config/api';

interface AdminState {
  sources: VideoSource[];
  interfaces: NetworkInterface[];
  loading: boolean;
  error: string | null;
}

export function useVideoSources() {
  const [state, setState] = useState<AdminState>({
    sources: [],
    interfaces: [],
    loading: false,
    error: null,
  });

  // ── 视频源 ──────────────────────────────────────────────────

  const fetchSources = useCallback(async () => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await fetch(getApiUrl('/api/v1/video-sources'));
      if (!res.ok) throw new Error(`获取视频源失败: HTTP ${res.status}`);
      const data = await res.json();
      setState(prev => ({ ...prev, sources: data.sources || [], loading: false }));
      return data.sources as VideoSource[];
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误';
      setState(prev => ({ ...prev, error: msg, loading: false }));
      return [];
    }
  }, []);

  const fetchActiveSources = useCallback(async () => {
    try {
      const res = await fetch(getApiUrl('/api/v1/video-sources/active'));
      if (!res.ok) throw new Error(`获取活跃视频源失败: HTTP ${res.status}`);
      const data = await res.json();
      return data.sources as VideoSource[];
    } catch (err) {
      console.error('获取活跃视频源失败:', err);
      return [];
    }
  }, []);

  const createSource = useCallback(async (req: VideoSourceRequest) => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await fetch(getApiUrl('/api/v1/video-sources'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `创建失败: HTTP ${res.status}`);
      }
      const data = await res.json();
      await fetchSources();
      return data.source as VideoSource;
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误';
      setState(prev => ({ ...prev, error: msg, loading: false }));
      throw err;
    }
  }, [fetchSources]);

  const updateSource = useCallback(async (sourceId: number, req: VideoSourceRequest) => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await fetch(getApiUrl(`/api/v1/video-sources/${sourceId}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `更新失败: HTTP ${res.status}`);
      }
      const data = await res.json();
      await fetchSources();
      return data.source as VideoSource;
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误';
      setState(prev => ({ ...prev, error: msg, loading: false }));
      throw err;
    }
  }, [fetchSources]);

  const deleteSource = useCallback(async (sourceId: number) => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await fetch(getApiUrl(`/api/v1/video-sources/${sourceId}`), {
        method: 'DELETE',
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `删除失败: HTTP ${res.status}`);
      }
      await fetchSources();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误';
      setState(prev => ({ ...prev, error: msg, loading: false }));
      throw err;
    }
  }, [fetchSources]);

  // ── 网口 ──────────────────────────────────────────────────

  const fetchInterfaces = useCallback(async () => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await fetch(getApiUrl('/api/v1/network-interfaces'));
      if (!res.ok) throw new Error(`获取网口配置失败: HTTP ${res.status}`);
      const data = await res.json();
      setState(prev => ({ ...prev, interfaces: data.interfaces || [], loading: false }));
      return data.interfaces as NetworkInterface[];
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误';
      setState(prev => ({ ...prev, error: msg, loading: false }));
      return [];
    }
  }, []);

  const createInterface = useCallback(async (req: NetworkInterfaceRequest) => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await fetch(getApiUrl('/api/v1/network-interfaces'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `创建失败: HTTP ${res.status}`);
      }
      const data = await res.json();
      await fetchInterfaces();
      return data.interface as NetworkInterface;
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误';
      setState(prev => ({ ...prev, error: msg, loading: false }));
      throw err;
    }
  }, [fetchInterfaces]);

  const updateInterface = useCallback(async (ifaceId: number, req: NetworkInterfaceRequest) => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await fetch(getApiUrl(`/api/v1/network-interfaces/${ifaceId}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `更新失败: HTTP ${res.status}`);
      }
      const data = await res.json();
      await fetchInterfaces();
      return data.interface as NetworkInterface;
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误';
      setState(prev => ({ ...prev, error: msg, loading: false }));
      throw err;
    }
  }, [fetchInterfaces]);

  const deleteInterface = useCallback(async (ifaceId: number) => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await fetch(getApiUrl(`/api/v1/network-interfaces/${ifaceId}`), {
        method: 'DELETE',
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `删除失败: HTTP ${res.status}`);
      }
      await fetchInterfaces();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误';
      setState(prev => ({ ...prev, error: msg, loading: false }));
      throw err;
    }
  }, [fetchInterfaces]);

  return {
    ...state,
    // 视频源
    fetchSources,
    fetchActiveSources,
    createSource,
    updateSource,
    deleteSource,
    // 网口
    fetchInterfaces,
    createInterface,
    updateInterface,
    deleteInterface,
  };
}
