import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ControlPad } from '../ControlPad'
import { ConsolePage, type ConsolePageProps } from './ConsolePage'
import { clearAuthState, setAuthState } from '../../stores/authStore'
import type { UseRobotControlReturn } from '../../hooks/useRobotControl'

vi.mock('../video/VideoStage', () => ({ VideoStage: () => <div>视频区域</div> }))
vi.mock('../console/ConsoleRightPanel', () => ({
  ConsoleRightPanel: ({ control }: { control: UseRobotControlReturn }) => <ControlPad control={control} />,
}))

const props: ConsolePageProps = {
  isUiFullscreen: false,
  // These components are replaced above; this test exercises the shared real control hook.
  videoStageProps: {} as ConsolePageProps['videoStageProps'],
  rightPanelProps: {} as ConsolePageProps['rightPanelProps'],
}

const requests: string[] = []
const response = (result = 'ACCEPTED', cmd = 'stop') => new Response(JSON.stringify({
  ack_cmd: cmd, result, latency_ms: 5,
}), { status: 200, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => {
  vi.useFakeTimers()
  requests.length = 0
  setAuthState({ accessToken: 'simulated-token', id: 1, username: 'operator', role: 'operator', must_change_password: false })
  vi.stubGlobal('fetch', vi.fn(async (url, init) => {
    const cmd = String(url).endsWith('/stop') ? 'stop' : JSON.parse(init.body).cmd
    requests.push(cmd)
    return response('ACCEPTED', cmd)
  }))
})

afterEach(() => {
  cleanup()
  clearAuthState()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

async function startForward() {
  fireEvent.click(screen.getByRole('button', { name: '开启控制' }))
  const button = screen.getByRole('button', { name: '前进' })
  button.setPointerCapture = vi.fn()
  await act(async () => fireEvent.pointerDown(button, { pointerId: 1, pointerType: 'touch' }))
  return button
}

describe('console shared manual stop', () => {
  it('cancels the same repeating command used by the touch pad and waits for an acknowledged stop', async () => {
    render(<ConsolePage {...props} />)
    await startForward()
    await act(() => vi.advanceTimersByTimeAsync(650))
    await act(async () => fireEvent.click(screen.getByRole('button', { name: '立即停车' })))
    await act(() => vi.advanceTimersByTimeAsync(1600))
    expect(requests).toEqual(['forward', 'forward', 'stop'])
    expect(within(screen.getByRole('region', { name: '手动停车' })).getByRole('status')).toHaveTextContent('手动停车已确认')
  })

  it.each(['pointerUp', 'pointerCancel', 'lostPointerCapture'] as const)('stops and cancels repeats on %s', async (event) => {
    render(<ConsolePage {...props} />)
    const forward = await startForward()
    await act(async () => fireEvent[event](forward, { pointerId: 1, pointerType: 'touch' }))
    await act(() => vi.advanceTimersByTimeAsync(1200))
    expect(requests).toEqual(['forward', 'stop'])
  })

  it('stops when fullscreen hides the touch pad and keeps the fixed stop available', async () => {
    const { rerender } = render(<ConsolePage {...props} />)
    await startForward()
    await act(async () => rerender(<ConsolePage {...props} isUiFullscreen />))
    await act(() => vi.advanceTimersByTimeAsync(1200))
    expect(requests).toEqual(['forward', 'stop'])
    expect(screen.queryByRole('button', { name: '前进' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '立即停车' })).toBeInTheDocument()
  })

  it('stops on leaving the console without leaving the repeating command alive', async () => {
    const { unmount } = render(<ConsolePage {...props} />)
    await startForward()
    await act(async () => unmount())
    await act(() => vi.advanceTimersByTimeAsync(1200))
    expect(requests).toEqual(['forward', 'stop'])
  })

  it('shows SDK rejection without claiming the robot has stopped', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response('REJECTED_ADAPTER_NOT_READY')))
    render(<ConsolePage {...props} />)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: '立即停车' })))
    const status = within(screen.getByRole('region', { name: '手动停车' })).getByRole('status')
    expect(status).toHaveTextContent('机器人控制适配器未就绪')
    expect(status).not.toHaveTextContent('停车已确认')
  })

  it('keeps the stop pending and blocks new motion while the adapter reply is delayed', async () => {
    let resolve!: (response: Response) => void
    const fetchMock = vi.fn(() => new Promise<Response>(done => { resolve = done }))
    vi.stubGlobal('fetch', fetchMock)
    render(<ConsolePage {...props} />)
    fireEvent.click(screen.getByRole('button', { name: '立即停车' }))
    expect(screen.getByRole('button', { name: '等待停车确认…' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '开启控制' }))
    const forward = screen.getByRole('button', { name: '前进' })
    forward.setPointerCapture = vi.fn()
    fireEvent.pointerDown(forward, { pointerId: 1 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await act(async () => resolve(response()))
    expect(within(screen.getByRole('region', { name: '手动停车' })).getByRole('status')).toHaveTextContent('手动停车已确认')
  })

  it('keeps transport failure visible and allows an explicit stop retry', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('simulated disconnection')))
    render(<ConsolePage {...props} />)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: '立即停车' })))
    const status = within(screen.getByRole('region', { name: '手动停车' })).getByRole('status')
    expect(status).toHaveTextContent('未取得停车确认')
    expect(status).not.toHaveTextContent('停车已确认')
    expect(screen.getByRole('button', { name: '立即停车' })).toBeEnabled()
  })

  it('preserves the operator permission gate', () => {
    setAuthState({ accessToken: 'viewer-token', id: 2, username: 'viewer', role: 'viewer', must_change_password: false })
    render(<ConsolePage {...props} />)
    expect(screen.getByRole('button', { name: '立即停车' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '开启控制' })).toBeDisabled()
    expect(requests).toEqual([])
  })
})
