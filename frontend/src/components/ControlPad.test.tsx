import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ControlPad } from './ControlPad'

const robotControl = vi.hoisted(() => ({
  currentCmd: null as 'forward' | null,
  isControlling: false,
  lastResult: null,
  resultMessage: null,
  startCommand: vi.fn(),
  stopCommand: vi.fn(),
}))

vi.mock('../hooks/useRobotControl', () => ({
  useRobotControl: () => robotControl,
}))

vi.mock('../stores/authStore', () => ({
  hasAuthSession: () => true,
  hasRole: () => true,
  useAuthState: vi.fn(),
}))

describe('ControlPad safety lock', () => {
  beforeEach(() => {
    robotControl.currentCmd = null
    robotControl.isControlling = false
    robotControl.startCommand.mockReset()
    robotControl.stopCommand.mockReset()
  })

  it('blocks pointer and keyboard commands until control is explicitly enabled', () => {
    render(<ControlPad />)

    const forwardButton = screen.getByRole('button', { name: '前进' }) as HTMLButtonElement
    forwardButton.setPointerCapture = vi.fn()
    expect(forwardButton).toBeDisabled()

    fireEvent.pointerDown(forwardButton)
    fireEvent.keyDown(window, { key: 'w' })
    expect(robotControl.startCommand).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '开启控制' }))
    expect(forwardButton).toBeEnabled()

    fireEvent.pointerDown(forwardButton, { pointerId: 1 })
    expect(robotControl.startCommand).toHaveBeenCalledWith('forward', { vx: 0.3 })
  })

  it('stops an active command when control is closed', () => {
    const { rerender } = render(<ControlPad />)
    fireEvent.click(screen.getByRole('button', { name: '开启控制' }))

    robotControl.currentCmd = 'forward'
    robotControl.isControlling = true
    rerender(<ControlPad />)

    fireEvent.click(screen.getByRole('button', { name: '关闭控制' }))
    expect(robotControl.stopCommand).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: '前进' })).toBeDisabled()
  })
})
