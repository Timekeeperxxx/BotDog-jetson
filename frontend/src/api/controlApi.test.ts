import { afterEach, describe, expect, it, vi } from 'vitest'
import { requestRobotStop, requestEmergencyStop } from './controlApi'

const fetchApi = vi.hoisted(() => vi.fn())
vi.mock('./apiFetch', () => ({ apiFetch: fetchApi }))
afterEach(() => { vi.restoreAllMocks(); fetchApi.mockReset() })

describe('control response contracts', () => {
  it('gives stop confirmation transport headroom beyond the backend 6s budget', async () => {
    const timeout = vi.spyOn(AbortSignal, 'timeout')
    fetchApi.mockResolvedValue({ ack_cmd: 'stop', result: 'ACCEPTED', latency_ms: 3000 })
    await requestRobotStop()
    expect(timeout).toHaveBeenCalledWith(8000)
  })

  it('keeps a refused SDK stop distinct from HTTP success', async () => {
    fetchApi.mockResolvedValue({ success: false, e_stop_latched: true, stop_confirmed: false, control_ack: null,
      errors: ['adapter unavailable'], timestamp: 'test', message: '急停已锁定，但未确认停车' })
    expect((await requestEmergencyStop()).stop_confirmed).toBe(false)
  })

  it('rejects an old success-only emergency response as unconfirmed', async () => {
    fetchApi.mockResolvedValue({ success: true, message: '紧急制动已触发' })
    await expect(requestEmergencyStop()).rejects.toThrow('未取得有效的急停与停车确认')
  })

  it('does not accept a malformed stop response', async () => {
    fetchApi.mockResolvedValue({ success: true })
    await expect(requestRobotStop()).rejects.toThrow('未取得有效的停车确认')
  })
})
