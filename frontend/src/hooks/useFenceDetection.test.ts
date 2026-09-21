import { act, renderHook, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { disableFenceDetection, enableFenceDetection, getFenceDetectionStatus } from '../api/fenceDetectionApi'
import type { FenceDetectionStatus } from '../types/fenceDetection'
import { useFenceDetection } from './useFenceDetection'

vi.mock('../api/fenceDetectionApi', () => ({
  disableFenceDetection: vi.fn(),
  enableFenceDetection: vi.fn(),
  getFenceDetectionStatus: vi.fn(),
}))

it('uses the manual APIs, syncs the returned status, and reports a failed toggle', async () => {
  let current: FenceDetectionStatus = {
    enabled: false, state: 'disabled', detail: '', scene_id: null, target_fence_id: null,
    target_point: null, distance_m: null, desired_yaw_deg: null, desired_pitch_deg: null,
    behavior: 'normal', behavior_track_id: null, persons: [], missing_calibration: [], gimbal_error: null,
  }
  vi.mocked(getFenceDetectionStatus).mockImplementation(async () => current)
  vi.mocked(enableFenceDetection).mockImplementation(async () => {
    current = { ...current, enabled: true, state: 'finding' }
    return current
  })
  vi.mocked(disableFenceDetection).mockRejectedValueOnce(new Error('云台停止失败'))
  const { result } = renderHook(() => useFenceDetection())
  await waitFor(() => expect(result.current.status?.enabled).toBe(false))
  await act(() => result.current.setEnabled(true))
  expect(enableFenceDetection).toHaveBeenCalledOnce()
  expect(result.current.status?.enabled).toBe(true)
  await act(() => result.current.setEnabled(false))
  expect(disableFenceDetection).toHaveBeenCalledOnce()
  expect(result.current.error).toBe('云台停止失败')
  expect(result.current.loading).toBe(false)
  expect(result.current.status?.enabled).toBe(true)
})
