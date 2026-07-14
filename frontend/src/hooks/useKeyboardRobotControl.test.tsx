import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { useKeyboardRobotControl } from './useKeyboardRobotControl'
import type { RobotCommand, RobotCommandOptions } from './useRobotControl'

type Controls = {
  startCommand: ReturnType<typeof vi.fn>
  stopCommand: ReturnType<typeof vi.fn>
}

function KeyboardHarness({ controls }: { controls: Controls }) {
  const [enabled, setEnabled] = useState(true)
  const [currentCmd, setCurrentCmd] = useState<RobotCommand | null>(null)
  const startCommand = (cmd: RobotCommand, options?: RobotCommandOptions) => {
    controls.startCommand(cmd, options)
    setCurrentCmd(cmd)
  }
  const stopCommand = () => {
    controls.stopCommand()
    setCurrentCmd(null)
  }

  const { linearSpeed, resetSpeeds, turnSpeed } = useKeyboardRobotControl({
    canOperate: true,
    enabled,
    isControlling: currentCmd !== null,
    currentCmd,
    startCommand,
    stopCommand,
  })

  return (
    <div>
      <span data-testid="linear-speed">{linearSpeed.toFixed(1)}</span>
      <span data-testid="turn-speed">{turnSpeed.toFixed(1)}</span>
      <button
        type="button"
        onClick={() => {
          if (enabled) resetSpeeds()
          setEnabled((value) => !value)
        }}
      >
        toggle
      </button>
    </div>
  )
}

describe('useKeyboardRobotControl', () => {
  it('starts mapped commands with the adjusted keyboard speed', () => {
    const controls: Controls = {
      startCommand: vi.fn(),
      stopCommand: vi.fn(),
    }

    render(<KeyboardHarness controls={controls} />)

    fireEvent.keyDown(window, { key: 'ArrowUp' })
    fireEvent.keyDown(window, { key: 'w' })
    fireEvent.keyUp(window, { key: 'w' })

    expect(screen.getByTestId('linear-speed')).toHaveTextContent('0.4')
    expect(controls.startCommand).toHaveBeenCalledWith('forward', { vx: 0.4 })
    expect(controls.stopCommand).toHaveBeenCalledTimes(1)
  })

  it('resets speed and stops active control when disabled', async () => {
    const controls: Controls = {
      startCommand: vi.fn(),
      stopCommand: vi.fn(),
    }

    render(<KeyboardHarness controls={controls} />)

    fireEvent.keyDown(window, { key: 'ArrowUp' })
    fireEvent.keyDown(window, { key: 'q' })
    fireEvent.click(screen.getByRole('button', { name: 'toggle' }))

    expect(screen.getByTestId('linear-speed')).toHaveTextContent('0.3')
    expect(screen.getByTestId('turn-speed')).toHaveTextContent('0.5')
    await waitFor(() => {
      expect(controls.stopCommand).toHaveBeenCalledTimes(1)
    })
  })
})
