import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MappingControlResponse } from '../../types/pcdMap'
import { getMappingStatus } from '../../api/pcdMapApi'
import { mappingCompletionTitle, useNavMappingControls } from './useNavMappingControls'

vi.mock('../../api/pcdMapApi', () => ({
  getMappingStatus: vi.fn(), setMappingEnabled: vi.fn(), checkRadarPreflight: vi.fn(),
}))
const saving: MappingControlResponse = {
  success: true, enabled: false, running: false, saving: true, saved: false,
  scene_name: 'Scene1_测试', map_dir: '/maps/test', pid: 1,
  map_pcd_candidates: [], ground_pcd_candidates: [], pcd_files: [], message: null,
  save_elapsed_seconds: 12, save_progress: { stage: 'map_merge', label: '合并原始地图', detail: '', baseline_saved: false },
}
const getStatus = vi.mocked(getMappingStatus)
const options = { canOperate: true, addLog: vi.fn(), refreshScenes: vi.fn().mockResolvedValue(undefined) }

beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); getStatus.mockReset() })
afterEach(() => { cleanup(); vi.useRealTimers() })

async function mount() {
  const hook = renderHook(() => useNavMappingControls(options))
  await act(async () => { await Promise.resolve() })
  return hook
}
async function advance(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms) })
}

describe('save status recovery and polling', () => {
  it('retries initial refresh recovery when the first status request is offline', async () => {
    getStatus.mockRejectedValueOnce(new Error('offline on refresh')).mockResolvedValue(saving)
    const { result } = await mount()
    expect(result.current.mappingSaving).toBe(false)
    await advance(3000)
    expect(result.current.mappingSaving).toBe(true)
    expect(result.current.mappingSaveStatus?.save_progress?.stage).toBe('map_merge')
  })

  it('recovers a save after refresh and consumes real phase updates', async () => {
    getStatus.mockResolvedValueOnce(saving).mockResolvedValue({ ...saving,
      save_progress: { stage: 'loop_map', label: '重建回环地图', detail: '', baseline_saved: false, completed: 64, total: 480 },
    })
    const { result } = await mount()
    expect(result.current.mappingSaving).toBe(true)
    expect(result.current.mappingSaveStatus?.save_progress?.stage).toBe('map_merge')
    await advance(500)
    expect(result.current.mappingSaveStatus?.save_progress?.completed).toBe(64)
    expect(getStatus).toHaveBeenCalledTimes(2)
  })

  it('retains the last stage during a disconnect and reconnects automatically', async () => {
    getStatus.mockResolvedValueOnce(saving).mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({ ...saving, save_elapsed_seconds: 18 })
    const { result } = await mount()
    await advance(500)
    expect(result.current.mappingSaving).toBe(true)
    expect(result.current.mappingSaveStatus?.save_progress?.stage).toBe('map_merge')
    expect(result.current.mappingProgressError).toContain('自动重连')
    await advance(3000)
    expect(result.current.mappingProgressError).toBeNull()
    expect(result.current.mappingSaveStatus?.save_elapsed_seconds).toBe(18)
  })

  it('reports a baseline save distinctly and refreshes scenes only after completion', async () => {
    getStatus.mockResolvedValueOnce(saving).mockResolvedValue({ ...saving, saving: false,
      saved: true, height_refinement_state: 'baseline_saved', message: '证据不足，保留基线',
    })
    const { result } = await mount()
    expect(options.refreshScenes).not.toHaveBeenCalled()
    await advance(500)
    expect(result.current.mappingSaving).toBe(false)
    expect(result.current.mappingNotice?.title).toBe('地图已保存，保留基线')
    await advance(500)
    expect(options.refreshScenes).toHaveBeenCalledOnce()
  })

  it('never treats failed optimization telemetry as successful standard map saving', () => {
    expect(mappingCompletionTitle({ ...saving, saved: false, height_refinement_state: 'height_refined' }))
      .toBe('地图保存未完成')
    expect(mappingCompletionTitle({ ...saving, saved: true, height_refinement_state: 'height_refined' }))
      .toBe('地图保存与高度优化完成')
  })
})
