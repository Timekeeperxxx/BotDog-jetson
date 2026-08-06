import { apiFetch } from './apiFetch'
import type { FenceDetectionStatus } from '../types/fenceDetection'

export function getFenceDetectionStatus(): Promise<FenceDetectionStatus> {
  return apiFetch('/api/v1/fence-detection/status')
}

export function enableFenceDetection(): Promise<FenceDetectionStatus> {
  return apiFetch('/api/v1/fence-detection/enable', { method: 'POST' })
}

export function disableFenceDetection(): Promise<FenceDetectionStatus> {
  return apiFetch('/api/v1/fence-detection/disable', { method: 'POST' })
}
