import { apiFetch } from './apiFetch'
import type { ControlAck } from '../hooks/useRobotControl'

// SDK stop confirmation is bounded at 6s. Leave transport/scheduling headroom;
// emergency stop also waits for navigation-channel cleanup in parallel.
export const STOP_REQUEST_TIMEOUT_MS = 8000
export const EMERGENCY_STOP_TIMEOUT_MS = 10000

export interface EmergencyStopResponse {
  success: boolean
  e_stop_latched: boolean
  stop_confirmed: boolean
  control_ack: ControlAck | null
  errors: string[]
  timestamp: string
  message: string
}

export async function requestRobotStop(): Promise<ControlAck> {
  const ack = await apiFetch<ControlAck>('/api/v1/control/stop', {
    method: 'POST', signal: AbortSignal.timeout(STOP_REQUEST_TIMEOUT_MS),
  })
  if (ack.ack_cmd !== 'stop' || typeof ack.result !== 'string') {
    throw new Error('未取得有效的停车确认')
  }
  return ack
}

export async function requestEmergencyStop(): Promise<EmergencyStopResponse> {
  const result = await apiFetch<EmergencyStopResponse>('/api/v1/control/e-stop', {
    method: 'POST', signal: AbortSignal.timeout(EMERGENCY_STOP_TIMEOUT_MS),
  })
  if (result.e_stop_latched !== true || typeof result.stop_confirmed !== 'boolean' || typeof result.message !== 'string') {
    throw new Error('未取得有效的急停与停车确认')
  }
  return result
}
