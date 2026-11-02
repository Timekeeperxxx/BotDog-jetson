import { act, fireEvent, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '../api/apiFetch'
import { useKeyboardGimbalControl } from './useKeyboardGimbalControl'

vi.mock('../api/apiFetch', () => ({ apiFetch: vi.fn() }))
const status = { connected: true }
const stop = { pitch_velocity_dps: 0, yaw_velocity_dps: 0 }
const commands = () => vi.mocked(apiFetch).mock.calls.map(([, init]) => JSON.parse(String(init?.body)))
async function settle() { await act(async () => { await Promise.resolve(); await Promise.resolve() }) }
function mount(enabled = true) {
  const onStatus = vi.fn(), onError = vi.fn()
  return { ...renderHook(({ active }) => useKeyboardGimbalControl({ enabled: active, onStatus, onError }), {
    initialProps: { active: enabled },
  }), onStatus, onError }
}

describe('keyboard gimbal control', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(apiFetch).mockReset().mockResolvedValue(status)
  })
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

  it.each([
    ['ArrowUp', 12, 0], ['ArrowDown', -12, 0], ['ArrowLeft', 0, -12], ['ArrowRight', 0, 12],
  ])('maps %s to the existing camera direction and stops on release', async (key, pitch, yaw) => {
    mount()
    fireEvent.keyDown(window, { key })
    await settle()
    expect(commands()).toEqual([{ pitch_velocity_dps: pitch, yaw_velocity_dps: yaw }])
    fireEvent.keyUp(window, { key })
    await settle()
    expect(commands().at(-1)).toEqual(stop)
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    expect(commands()).toHaveLength(2)
  })

  it('refreshes a held key without relying on OS key-repeat', async () => {
    mount()
    fireEvent.keyDown(window, { key: 'ArrowUp' })
    await settle()
    fireEvent.keyDown(window, { key: 'ArrowUp', repeat: true })
    expect(commands()).toHaveLength(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(600) })
    expect(commands()).toHaveLength(4)
    expect(commands().every(c => c.pitch_velocity_dps === 12)).toBe(true)
  })

  it('keeps the other axis moving after a diagonal key is released', async () => {
    mount()
    fireEvent.keyDown(window, { key: 'ArrowUp' }); await settle()
    fireEvent.keyDown(window, { key: 'ArrowLeft' }); await settle()
    expect(commands().at(-1)).toEqual({ pitch_velocity_dps: 12, yaw_velocity_dps: -12 })
    fireEvent.keyUp(window, { key: 'ArrowUp' }); await settle()
    expect(commands().at(-1)).toEqual({ pitch_velocity_dps: 0, yaw_velocity_dps: -12 })
    fireEvent.keyUp(window, { key: 'ArrowLeft' }); await settle()
    expect(commands().at(-1)).toEqual(stop)
  })

  it('takes priority over the body speed handler and page scrolling', async () => {
    const bodyHandler = vi.fn()
    window.addEventListener('keydown', bodyHandler)
    try {
      mount()
      const event = new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true })
      act(() => { window.dispatchEvent(event) })
      await settle()
      expect(event.defaultPrevented).toBe(true)
      expect(bodyHandler).not.toHaveBeenCalled()
    } finally { window.removeEventListener('keydown', bodyHandler) }
  })

  it.each(['input', 'textarea', 'select', 'editable', 'slider', 'tab', 'dialog'])('leaves %s arrow handling alone', async kind => {
    mount()
    const target = document.createElement(['input','textarea','select'].includes(kind) ? kind : 'div')
    if (kind === 'editable') target.setAttribute('contenteditable','true')
    if (['slider','tab','dialog'].includes(kind)) target.setAttribute('role',kind)
    document.body.append(target)
    try {
      fireEvent.keyDown(target, { key: 'ArrowUp' })
      fireEvent.keyUp(target, { key: 'ArrowUp' })
      await settle()
      expect(apiFetch).not.toHaveBeenCalled()
    } finally { target.remove() }
  })

  it.each(['blur','hidden','disabled','unmount','input-focus'])('stops when %s interrupts a held key', async reason => {
    const hook = mount()
    fireEvent.keyDown(window, { key: 'ArrowUp' }); await settle()
    if (reason === 'blur') fireEvent.blur(window)
    if (reason === 'hidden') {
      vi.spyOn(document,'hidden','get').mockReturnValue(true)
      fireEvent(document,new Event('visibilitychange'))
    }
    if (reason === 'disabled') hook.rerender({active:false})
    if (reason === 'unmount') hook.unmount()
    if (reason === 'input-focus') {
      const input = document.createElement('input');document.body.append(input)
      fireEvent.focusIn(input);input.remove()
    }
    await settle()
    expect(commands().at(-1)).toEqual(stop)
    const length = commands().length
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(commands()).toHaveLength(length)
  })

  it('queues the final stop after a slow movement request and drops stale heartbeats', async () => {
    let resolve!: (value: unknown) => void
    vi.mocked(apiFetch).mockImplementationOnce(() => new Promise(r => { resolve = r }))
    mount()
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    await act(async () => { await vi.advanceTimersByTimeAsync(600) })
    expect(apiFetch).toHaveBeenCalledTimes(1)
    fireEvent.keyUp(window, { key: 'ArrowLeft' })
    await act(async () => { resolve(status); await Promise.resolve() })
    await settle()
    expect(commands()).toEqual([{pitch_velocity_dps:0,yaw_velocity_dps:-12},stop])
  })

  it('clears held keys on request failure and attempts only one stop', async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(new Error('connection lost')).mockRejectedValueOnce(new Error('offline'))
    const hook = mount()
    fireEvent.keyDown(window, { key:'ArrowUp' }); await settle()
    expect(hook.onError).toHaveBeenCalledWith('connection lost')
    expect(commands().at(-1)).toEqual(stop)
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    expect(apiFetch).toHaveBeenCalledTimes(2)
  })

  it('does not issue a stop or capture keys while disabled or idle', async () => {
    const hook = mount(false)
    fireEvent.keyDown(window, {key:'ArrowUp'})
    hook.rerender({active:true})
    fireEvent.blur(window)
    hook.unmount()
    await settle()
    expect(apiFetch).not.toHaveBeenCalled()
  })
})
