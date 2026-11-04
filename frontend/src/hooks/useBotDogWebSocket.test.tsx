import { act, renderHook, cleanup } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useBotDogWebSocket } from './useBotDogWebSocket'

const emergency = vi.hoisted(() => vi.fn())
vi.mock('../api/controlApi', () => ({ requestEmergencyStop: emergency }))

class FakeWebSocket {
  static OPEN = 1; static CONNECTING = 0; static CLOSED = 3
  readyState = 0
  close() { this.readyState = 3 }
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks() })

describe('emergency stop feedback', () => {
  it('does not equate an HTTP success with confirmed braking', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    emergency.mockResolvedValue({ success: false, e_stop_latched: true, stop_confirmed: false, message: '急停已锁定，但底盘停车未确认' })
    const { result } = renderHook(() => useBotDogWebSocket())
    await act(async () => result.current.triggerEmergencyStop())
    expect(result.current.logs.at(-1)?.message).toContain('停车未确认')
    expect(result.current.logs.at(-1)?.level).toBe('error')
  })

  it('leaves a lost response explicitly unconfirmed', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    emergency.mockRejectedValue(new Error('network down'))
    const { result } = renderHook(() => useBotDogWebSocket())
    await act(async () => result.current.triggerEmergencyStop())
    expect(result.current.logs.at(-1)?.message).toContain('未取得确认')
  })
})
