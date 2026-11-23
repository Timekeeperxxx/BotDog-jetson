import { apiFetch } from './apiFetch'

export type GasAlarm = {
  channel: string
  severity: 'WARNING' | 'CRITICAL'
  kind: 'concentration' | 'sensor'
  message: string
  stale: boolean
}

export type GasMonitorSnapshot = {
  read_at: string
  alerts: GasAlarm[]
}

export function getGasMonitor(signal: AbortSignal): Promise<GasMonitorSnapshot> {
  return apiFetch('/api/v1/gases', { signal, cache: 'no-store' })
}
