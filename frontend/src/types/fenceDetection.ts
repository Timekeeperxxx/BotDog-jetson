export type FenceDetectionState =
  | 'disabled'
  | 'finding'
  | 'gimbal_moving'
  | 'detecting'
  | 'not_found'
  | 'out_of_range'
  | 'localization_unavailable'
  | 'calibration_unavailable'

export type FenceBehavior =
  | 'normal'
  | 'approaching'
  | 'dwelling'
  | 'contact'
  | 'climbing_suspected'
  | 'tampering_suspected'
  | 'tampering_confirmed'

export type FenceDetectionStatus = {
  enabled: boolean
  state: FenceDetectionState
  detail: string
  scene_id: string | null
  target_fence_id: string | null
  target_point: { x: number; y: number } | null
  distance_m: number | null
  desired_yaw_deg: number | null
  desired_pitch_deg: number | null
  behavior: FenceBehavior
  behavior_track_id: number | null
  persons: Array<{
    track_id: number
    behavior: FenceBehavior
    tamper_action_score: number
    duration_seconds: number
  }>
  tamper: {
    enabled: boolean
    structure_check_enabled: boolean
    reference_ready: boolean
    reference_age_seconds: number | null
    pending: boolean
    pending_track_id: number | null
    action_score: number
    structure_change_ratio: number
    last_result: FenceBehavior | null
    last_result_age_seconds: number | null
  }
  missing_calibration: string[]
  gimbal_error: string | null
}
