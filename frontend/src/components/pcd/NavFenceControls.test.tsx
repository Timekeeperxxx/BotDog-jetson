import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { NavFenceControls } from './NavFenceControls'
import type { FenceDetectionState, FenceDetectionStatus } from '../../types/fenceDetection'

const status = (state: FenceDetectionState): FenceDetectionStatus => ({
  enabled: true, state, detail: '', scene_id: null, target_fence_id: null,
  target_point: null, distance_m: null, desired_yaw_deg: null, desired_pitch_deg: null,
  behavior: 'normal', behavior_track_id: null, persons: [],
  tamper: {
    enabled: false, structure_check_enabled: false, reference_ready: false,
    reference_age_seconds: null, pending: false, pending_track_id: null,
    action_score: 0, structure_change_ratio: 0, last_result: null, last_result_age_seconds: null,
  },
  missing_calibration: [], gimbal_error: null,
})

describe('动作判定与云台观察状态', () => {
  it.each<FenceDetectionState>(['not_found', 'localization_unavailable', 'gimbal_moving', 'tracking', 'detecting'])(
    '观察状态为 %s 时仍说明动作检测已开启', (state) => {
      render(<NavFenceControls adding={false} canAdd canOperate status={status(state)}
        loading={false} error={null} onToggleAdd={vi.fn()} onSetDetectionEnabled={vi.fn()} />)
      expect(screen.getByText('动作检测已开启')).toBeInTheDocument()
      expect(screen.queryByText(/破坏复核|建立基准|接触围栏|人员 正常/)).not.toBeInTheDocument()
    },
  )
})
