import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getLocalizationDiagnostics, type LocalizationDiagnostics } from '../../api/pcdMapApi'
import { useLocalizationDiagnostics } from './useLocalizationDiagnostics'

vi.mock('../../api/pcdMapApi', () => ({ getLocalizationDiagnostics: vi.fn() }))
const snapshot: LocalizationDiagnostics = {
  scene_id: 'scene-a', phase: 'fallback', level: 'error', match: 'fallback',
  message: '偏移超限，已回退到手动位姿', navigation_ready: true, events: [],
}
afterEach(() => { vi.useRealTimers(); vi.resetAllMocks() })

describe('localization diagnostics', () => {
  it('keeps fallback warning even when runtime is ready', async () => {
    vi.mocked(getLocalizationDiagnostics).mockResolvedValue(snapshot)
    const { result } = renderHook(() => useLocalizationDiagnostics('scene-a', true))
    await waitFor(() => expect(result.current?.phase).toBe('fallback'))
    expect(result.current?.level).toBe('error')
  })

  it('ignores responses from a previous scene', async () => {
    let resolve!: (value: LocalizationDiagnostics) => void
    vi.mocked(getLocalizationDiagnostics).mockImplementation(() => new Promise((done) => { resolve = done }))
    const { result, rerender } = renderHook(({ scene, enabled }) => useLocalizationDiagnostics(scene, enabled), {
      initialProps: { scene: 'scene-a', enabled: true },
    })
    rerender({ scene: 'scene-b', enabled: false })
    await act(async () => resolve(snapshot))
    expect(result.current).toBeNull()
  })

  it('replaces stale success when diagnostics cannot be refreshed', async () => {
    vi.useFakeTimers()
    vi.mocked(getLocalizationDiagnostics)
      .mockResolvedValueOnce({ ...snapshot, phase: 'ready', level: 'info', match: 'matched' })
      .mockRejectedValueOnce(new Error('连接断开'))
    const { result } = renderHook(() => useLocalizationDiagnostics('scene-a', true))
    await act(async () => {})
    expect(result.current?.phase).toBe('ready')
    await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
    expect(result.current?.phase).toBe('connection')
    expect(result.current?.navigation_ready).toBe(false)
    expect(result.current?.message).toContain('状态未知')
  })
})
