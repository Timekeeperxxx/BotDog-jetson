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
    onSelectTask: vi.fn(),
    onEditTask: vi.fn(),
    onExecuteTask: vi.fn(),
    onStopTask: vi.fn(),
    onDeleteTask: vi.fn(),
    onStartCreate: vi.fn(),
    ...overrides,
  }
  render(<TaskDrawerPanel {...props} />)
  return props
}

describe('TaskDrawerPanel', () => {
  it('executes the clicked task instead of depending on the selected task card', async () => {
    const user = userEvent.setup()
    const props = renderPanel()

    const executeButtons = screen.getAllByRole('button', { name: '执行' })
    await user.click(executeButtons[1])

    expect(props.onExecuteTask).toHaveBeenCalledWith('task-current-scene')
  })

  it('shows immediate startup feedback and prevents duplicate starts', () => {
    renderPanel({ executingTaskId: 'task-current-scene' })

    expect(screen.getByRole('button', { name: '启动中…' })).toBeDisabled()
    for (const button of screen.getAllByRole('button', { name: '执行' })) {
      expect(button).toBeDisabled()
    }
    expect(screen.getByText('启动中')).toBeInTheDocument()
  })
})
