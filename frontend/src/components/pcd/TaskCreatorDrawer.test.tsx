import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { TaskCreatorDrawer } from './TaskCreatorDrawer'
import { patchTaskDraftStep } from '../../pages/nav/navPageUtils'
import type { TaskDraft } from '../../types/taskWorkflow'

it('offers fence detection on/off in the task step selector', async () => {
  const user = userEvent.setup()
  function Editor() {
    const [draft, setDraft] = useState<TaskDraft>({
      name: '围栏巡检', mapId: 'scene', steps: [{ type: 'navigate_waypoint', waypointId: 'a' }],
    })
    return <TaskCreatorDrawer
      mode="create" draft={draft} selectedSceneId="scene" selectedSceneName="测试场景"
      selectedSceneWaypoints={[{ id: 'a', name: 'A点' }]} selectedSceneNavigable
      selectedSceneMessage={null} canSaveTask onDraftChange={vi.fn()} onAddDraftStep={vi.fn()}
      onRemoveDraftWaypoint={vi.fn()} onCancelCreate={vi.fn()} onCreateTask={vi.fn()}
      onDraftStepChange={(index, patch) => setDraft(current => patchTaskDraftStep(current, index, patch))}
    />
  }
  render(<Editor />)
  await user.selectOptions(screen.getByRole('combobox', { name: '第 1 步类型' }), 'fence_detection_control')
  expect(screen.getByRole('option', { name: '开启围栏检测' })).toBeInTheDocument()
  expect(screen.getByText('已选：开启围栏检测')).toBeInTheDocument()
  await user.selectOptions(screen.getByRole('combobox', { name: '第 1 步选项' }), 'disabled')
  expect(screen.getByText('已选：关闭围栏检测')).toBeInTheDocument()
})
