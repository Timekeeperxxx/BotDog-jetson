import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { TaskDefinition } from '../../types/taskWorkflow'
import { TaskDrawerPanel } from './TaskDrawerPanel'

const tasks: TaskDefinition[] = [
  {
    id: 'task-old-scene',
    name: '旧场景任务',
    mapId: 'SceneOld',
    mapName: 'SceneOld',
    createdAt: '2026-07-15T00:00:00Z',
    steps: [],
  },
  {
    id: 'task-current-scene',
    name: '当前场景任务',
    mapId: 'Scene21',
    mapName: 'Scene21',
    createdAt: '2026-07-15T00:00:00Z',
    steps: [],
  },
]

function renderPanel(overrides: Partial<React.ComponentProps<typeof TaskDrawerPanel>> = {}) {
  const props: React.ComponentProps<typeof TaskDrawerPanel> = {
    tasks,
    sceneName: 'Scene21',
    selectedTaskId: 'task-old-scene',
    navigationStatus: null,
    canStartCreate: true,
    canExecuteTask: true,
    canStopTask: true,
    executingTaskId: null,
    taskLoopEnabled: {},
    onSelectTask: vi.fn(),
    onEditTask: vi.fn(),
    onExecuteTask: vi.fn(),
    onTaskLoopChange: vi.fn(),
    onStopTask: vi.fn(),
    onDeleteTask: vi.fn(),
    onStartCreate: vi.fn(),
    ...overrides,
  }
  const { rerender } = render(<TaskDrawerPanel {...props} />)
  return {
    ...props,
    setLoopEnabled: (enabled: boolean) => {
      rerender(<TaskDrawerPanel {...props} taskLoopEnabled={{ 'task-current-scene': enabled }} />)
    },
  }
}

describe('TaskDrawerPanel', () => {
  it('executes the clicked task instead of depending on the selected task card', async () => {
    const user = userEvent.setup()
    const props = renderPanel()

    const executeButtons = screen.getAllByRole('button', { name: '执行' })
    await user.click(executeButtons[1])

    expect(props.onExecuteTask).toHaveBeenCalledWith('task-current-scene', false)
  })

  it('sets loop mode for one task without starting it', async () => {
    const user = userEvent.setup()
    const props = renderPanel()
    const currentSwitch = screen.getByRole('switch', { name: '当前场景任务 循环执行' })
    const otherSwitch = screen.getByRole('switch', { name: '旧场景任务 循环执行' })
    const executeButtons = screen.getAllByRole('button', { name: '执行' })

    expect(currentSwitch).not.toBeChecked()
    await user.click(currentSwitch)
    expect(props.onTaskLoopChange).toHaveBeenLastCalledWith('task-current-scene', true)
    expect(props.onExecuteTask).not.toHaveBeenCalled()
    expect(props.onSelectTask).not.toHaveBeenCalled()

    props.setLoopEnabled(true)
    expect(currentSwitch).toBeChecked()
    expect(otherSwitch).not.toBeChecked()
    await user.click(executeButtons[1])
    expect(props.onExecuteTask).toHaveBeenLastCalledWith('task-current-scene', true)

    await user.click(currentSwitch)
    expect(props.onTaskLoopChange).toHaveBeenLastCalledWith('task-current-scene', false)
    expect(props.onExecuteTask).toHaveBeenCalledTimes(1)
  })

  it('shows immediate startup feedback and prevents duplicate starts', () => {
    renderPanel({ executingTaskId: 'task-current-scene' })

    expect(screen.getByRole('button', { name: '启动中…' })).toBeDisabled()
    for (const button of screen.getAllByRole('button', { name: '执行' })) {
      expect(button).toBeDisabled()
    }
    for (const button of screen.getAllByRole('switch')) {
      expect(button).toBeDisabled()
    }
    expect(screen.getByText('启动中')).toBeInTheDocument()
  })
})
