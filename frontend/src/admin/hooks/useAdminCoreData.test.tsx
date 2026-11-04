import { act, renderHook, cleanup } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAdminCoreData } from './useAdminCoreData'

const health = vi.hoisted(() => vi.fn())
vi.mock('../adminApi', () => ({
  getSystemHealth: health,
  getSystemInfo: vi.fn().mockResolvedValue({ groups: [] }),
  getSystemResources: vi.fn().mockResolvedValue(null),
  getAdminLogs: vi.fn().mockResolvedValue({ items: [] }),
}))
vi.mock('../../api/navApi', () => ({ getNavState: vi.fn().mockResolvedValue(null) }))

beforeEach(() => { vi.useFakeTimers(); health.mockReset() })
afterEach(() => { cleanup(); vi.useRealTimers() })

describe('live health polling', () => {
  it('replaces stale health and shows a failed poll as unavailable', async () => {
    health.mockResolvedValue({ status: 'healthy', ready: true })
    const { result } = renderHook(() => useAdminCoreData())
    await act(async () => {})
    expect(result.current.health?.ready).toBe(true)
    health.mockResolvedValue({ status: 'degraded', ready: false })
    await act(() => vi.advanceTimersByTimeAsync(5000))
    expect(result.current.health?.ready).toBe(false)
    health.mockRejectedValue(new Error('offline'))
    await act(() => vi.advanceTimersByTimeAsync(5000))
    expect(result.current.health).toBeNull()
    expect(result.current.adminError).toContain('实时健康状态读取失败')
    health.mockResolvedValue({ status: 'healthy', ready: true })
    await act(() => vi.advanceTimersByTimeAsync(5000))
    expect(result.current.health?.ready).toBe(true)
    expect(result.current.adminError).toBeNull()
  })

  it('aborts a poll when the view unmounts', async () => {
    health.mockResolvedValueOnce({ status: 'healthy', ready: true }).mockReturnValue(new Promise(() => {}))
    const { unmount } = renderHook(() => useAdminCoreData())
    await act(async () => {})
    await act(() => vi.advanceTimersByTimeAsync(5000))
    const signal = health.mock.calls.at(-1)?.[0]
    expect(signal.aborted).toBe(false)
    unmount()
    expect(signal.aborted).toBe(true)
  })
})
