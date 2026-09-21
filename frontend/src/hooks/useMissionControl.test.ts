import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useMissionControl } from './useMissionControl';

afterEach(() => vi.unstubAllGlobals());

it('restores a running task after refresh and stops that task without starting another', async () => {
  let current: { task_id: number } | null = { task_id: 5 };
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/session/stop')) {
      expect(JSON.parse(options?.body as string)).toEqual({ task_id: 5 });
      current = null;
    }
    return { ok: true, json: async () => current };
  });
  vi.stubGlobal('fetch', fetchMock);
  const addLog = vi.fn();
  const { result } = renderHook(() => useMissionControl(addLog));
  await waitFor(() => expect(result.current.missionTaskId).toBe(5));
  await act(() => result.current.toggleMission());
  expect(result.current.isMissionRunning).toBe(false);
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/session/start'))).toBe(false);
});

it('keeps the running state when stopping fails', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: !url.endsWith('/session/stop'), status: 500,
    json: async () => ({ task_id: 5 }),
  })));
  const addLog = vi.fn();
  const { result } = renderHook(() => useMissionControl(addLog));
  await waitFor(() => expect(result.current.isMissionRunning).toBe(true));
  await act(() => result.current.toggleMission());
  expect(result.current.isMissionRunning).toBe(true);
  expect(addLog).toHaveBeenCalledWith(expect.stringContaining('停止巡检失败'), 'error', 'MISSION');
});
