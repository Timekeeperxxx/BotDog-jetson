import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { NavWaypoint } from '../../types/pcdMap'
import { GoToWaypointConfirmDialog } from './NavPageDialogs'

const waypoint: NavWaypoint = {
  id: 'waypoint-1',
  map_id: 'Scene5',
  name: '测试点',
  x: 4.2,
  y: -1.3,
  z: 0.6,
  yaw: 1.57,
  frame_id: 'map',
  created_at: '2026-07-28T00:00:00Z',
  updated_at: '2026-07-28T00:00:00Z',
}

describe('GoToWaypointConfirmDialog', () => {
  it('locks both actions while the navigation request is being submitted', async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()
    const onConfirm = vi.fn()

    render(
      <GoToWaypointConfirmDialog
        waypoint={waypoint}
        sending
        onCancel={onCancel}
        onConfirm={onConfirm}
      />,
    )

    const cancelButton = screen.getByRole('button', { name: '取消' })
    const confirmButton = screen.getByRole('button', { name: '正在提交…' })
    expect(cancelButton).toBeDisabled()
    expect(confirmButton).toBeDisabled()

    await user.click(cancelButton)
    await user.click(confirmButton)
    expect(onCancel).not.toHaveBeenCalled()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('submits the selected waypoint when idle', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()

    render(
      <GoToWaypointConfirmDialog
        waypoint={waypoint}
        sending={false}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />,
    )

    await user.click(screen.getByRole('button', { name: '确认导航' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onConfirm).toHaveBeenCalledWith(waypoint)
  })
})
