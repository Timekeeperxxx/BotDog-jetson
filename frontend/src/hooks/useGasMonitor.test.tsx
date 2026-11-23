import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getGasMonitor, type GasMonitorSnapshot } from '../api/gasMonitorApi'
import { useGasMonitor } from './useGasMonitor'

vi.mock('../api/gasMonitorApi', () => ({ getGasMonitor: vi.fn() }))
const getMonitor = vi.mocked(getGasMonitor)
const alarm: GasMonitorSnapshot = { read_at: '2026-10-29T10:00:00+08:00', alerts: [
  { channel: 'ph3', severity: 'CRITICAL', kind: 'concentration', message: '磷化氢 25.0 ppm · 超过上限', stale: false },
] }

describe('useGasMonitor', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks() })
  afterEach(() => { vi.useRealTimers() })

  it('loads immediately and clears an alarm only when a fresh normal snapshot arrives', async () => {
    getMonitor.mockResolvedValueOnce(alarm).mockResolvedValue({ ...alarm, alerts: [] })
    const hook = renderHook(() => useGasMonitor())
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(hook.result.current.alerts).toEqual(alarm.alerts)
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    expect(hook.result.current).toEqual({ state: 'ready', alerts: [], error: null })
  })

  it('keeps the last alarm and exposes an outage instead of showing normal', async () => {
    getMonitor.mockResolvedValueOnce(alarm).mockRejectedValue(new Error('无法连接气体监测服务'))
    const hook = renderHook(() => useGasMonitor())
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    expect(hook.result.current.state).toBe('unavailable')
    expect(hook.result.current.error).toBe('无法连接气体监测服务')
    expect(hook.result.current.alerts).toEqual(alarm.alerts)
  })

  it('expires previous results if a later request stalls and does not overlap requests', async () => {
    getMonitor.mockResolvedValueOnce(alarm).mockImplementation(() => new Promise(() => {}))
    const hook = renderHook(() => useGasMonitor())
    await act(async () => { await vi.advanceTimersByTimeAsync(15001) })
    expect(getMonitor).toHaveBeenCalledTimes(2)
    expect(hook.result.current.state).toBe('unavailable')
    expect(hook.result.current.alerts).toEqual(alarm.alerts)
  })

  it('aborts a timed out request and cancels polling on unmount', async () => {
    let signal: AbortSignal
    getMonitor.mockImplementation((currentSignal) => {
      signal = currentSignal
      return new Promise((_, reject) => signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
    })
    const hook = renderHook(() => useGasMonitor())
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(signal!.aborted).toBe(true)
    expect(hook.result.current.error).toBe('气体监测请求超时')
    hook.unmount()
    await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
    expect(getMonitor).toHaveBeenCalledTimes(1)
  })
})
