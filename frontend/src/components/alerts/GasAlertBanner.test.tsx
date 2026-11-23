import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useGasMonitor } from '../../hooks/useGasMonitor'
import { GasAlertBanner } from './GasAlertBanner'

vi.mock('../../hooks/useGasMonitor', () => ({ useGasMonitor: vi.fn() }))
vi.mock('../../config/api', () => ({ getApiBaseUrl: () => 'http://192.168.8.2:8001' }))
const monitor = vi.mocked(useGasMonitor)

describe('GasAlertBanner', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('does not show a banner for fresh normal data', () => {
    monitor.mockReturnValue({ state: 'ready', alerts: [], error: null })
    render(<GasAlertBanner />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows all current alarms and links to the actual gas service', () => {
    monitor.mockReturnValue({ state: 'ready', error: null, alerts: [
      { channel: 'ph3', severity: 'CRITICAL', kind: 'concentration', message: '磷化氢（PH₃）25.0 ppm · 高报', stale: false },
      { channel: 'o2', severity: 'CRITICAL', kind: 'concentration', message: '氧气（O₂）18.0 % vol · 低于下限', stale: false },
    ] })
    render(<GasAlertBanner />)
    expect(screen.getByRole('alert')).toHaveClass('is-critical')
    expect(screen.getByText(/磷化氢/)).toBeInTheDocument()
    expect(screen.getByText(/氧气/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看气体' })).toHaveAttribute('href', 'http://192.168.8.2:8787/gases')
  })

  it('separates sensor failure from a gas concentration alert', () => {
    monitor.mockReturnValue({ state: 'ready', error: null, alerts: [
      { channel: 'co2', severity: 'WARNING', kind: 'sensor', message: '二氧化碳（CO₂） · 传感器故障', stale: false },
    ] })
    render(<GasAlertBanner />)
    expect(screen.getByRole('alert')).toHaveClass('is-warning')
    expect(screen.getByText(/传感器故障/)).toBeInTheDocument()
  })

  it('marks retained alarms as historical during an outage', () => {
    monitor.mockReturnValue({ state: 'unavailable', error: '气体监测请求超时', alerts: [
      { channel: 'ph3', severity: 'CRITICAL', kind: 'concentration', message: '磷化氢 25.0 ppm · 高报', stale: false },
    ] })
    render(<GasAlertBanner />)
    expect(screen.getByText('气体监测请求超时')).toBeInTheDocument()
    expect(screen.getByText('上次：磷化氢 25.0 ppm · 高报')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveClass('is-critical')
  })
})
