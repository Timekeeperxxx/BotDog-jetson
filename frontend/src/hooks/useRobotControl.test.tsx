import { act, renderHook, cleanup } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRobotControl } from './useRobotControl'
import { clearAuthState, setAuthState } from '../stores/authStore'
import { STOP_REQUEST_TIMEOUT_MS } from '../api/controlApi'

const ack = (result = 'ACCEPTED', cmd = 'stop') => new Response(
  JSON.stringify({ ack_cmd: cmd, result, latency_ms: 3000 }),
  { status: 200, headers: { 'Content-Type': 'application/json' } },
)

beforeEach(() => {
  vi.useFakeTimers()
  vi.spyOn(AbortSignal, 'timeout').mockImplementation((milliseconds) => {
    const controller = new AbortController()
    setTimeout(() => controller.abort(new DOMException('test timeout', 'TimeoutError')), milliseconds)
    return controller.signal
  })
})
afterEach(() => { cleanup(); clearAuthState(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers() })

describe('acknowledged robot stopping', () => {
  it('waits beyond 2s and confirms only after the actual SDK reply', async () => {
    let resolve!: (response: Response) => void
    const fetchMock = vi.fn().mockReturnValue(new Promise<Response>((done) => { resolve = done }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRobotControl())
    act(() => result.current.stopCommand())
    expect(result.current.stopStatus).toBe('waiting')
    await act(() => vi.advanceTimersByTimeAsync(2500))
    expect(result.current.stopStatus).toBe('waiting')
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(false)
    act(() => result.current.startCommand('forward'))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await act(async () => { resolve(ack()) })
    expect(result.current.stopStatus).toBe('confirmed')
    expect(result.current.lastResult?.result).toBe('ACCEPTED')
  })

  it('reports unconfirmed rather than inventing an SDK failure when HTTP times out', async () => {
    vi.stubGlobal('fetch', vi.fn((_url, init) => new Promise<Response>((_resolve, reject) => {
      init.signal.addEventListener('abort', () => reject(init.signal.reason))
    })))
    const { result } = renderHook(() => useRobotControl())
    act(() => result.current.stopCommand())
    await act(() => vi.advanceTimersByTimeAsync(STOP_REQUEST_TIMEOUT_MS))
    expect(result.current.stopStatus).toBe('unconfirmed')
    expect(result.current.lastResult).toBeNull()
    expect(result.current.resultMessage).toContain('未取得停车确认')
  })

  it('shows an actual SDK rejection even when HTTP status is 200', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ack('REJECTED_ADAPTER_NOT_READY')))
    const { result } = renderHook(() => useRobotControl())
    await act(async () => result.current.stopCommand())
    expect(result.current.stopStatus).toBe('failed')
    expect(result.current.resultMessage).toContain('适配器未就绪')
  })

  it('carries Bearer authentication on the unload keepalive stop request', async () => {
    setAuthState({ accessToken: 'fake-test-token', id: 1, username: 'operator', role: 'operator', must_change_password: false })
    const fetchMock = vi.fn().mockImplementation((url) => Promise.resolve(ack('ACCEPTED', String(url).includes('/command') ? 'forward' : 'stop')))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRobotControl())
    await act(async () => result.current.startCommand('forward'))
    await act(async () => window.dispatchEvent(new Event('beforeunload')))
    const request = fetchMock.mock.calls.find(([, init]) => init.keepalive)
    expect(request?.[1].headers.get('Authorization')).toBe('Bearer fake-test-token')
    act(() => result.current.stopCommand())
    await act(async () => {})
  })
})
