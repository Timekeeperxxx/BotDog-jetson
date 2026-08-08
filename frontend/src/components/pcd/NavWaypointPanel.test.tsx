import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { NavWaypoint } from '../../types/pcdMap'
import { NavWaypointPanel } from './NavWaypointPanel'

vi.mock('../../stores/authStore', () => ({
  hasAuthSession: () => true,
  hasRole: () => true,
  useAuthState: vi.fn(),
}))

const waypoints: NavWaypoint[] = [
  {
    id: 'wp_001',
    map_id: 'Scene5',
    name: '巡检点1',
    x: 1,
    y: 2,
    z: 0,
    yaw: 0,
    frame_id: 'map',
    created_at: '2026-08-08T00:00:00Z',
    updated_at: '2026-08-08T00:00:00Z',
  },
  {
    id: 'wp_002',
    map_id: 'Scene5',
    name: '巡检点2',
    x: 3,
    y: 4,
    z: 0,
    yaw: 1,
    frame_id: 'map',
    created_at: '2026-08-08T00:00:00Z',
    updated_at: '2026-08-08T00:00:00Z',
  },
]

describe('NavWaypointPanel', () => {
  it('keeps other targets clickable while the current goal request is in flight', async () => {
    const user = userEvent.setup()
    const onGoTo = vi.fn()

    render(
      <NavWaypointPanel
        waypoints={waypoints}
        goToSending
        navigatingWaypointId="wp_001"
        sceneNavigable
        onGoTo={onGoTo}
        onDelete={vi.fn()}
      />,
    )

    expect(screen.getByTitle('导航到该点')).toBeDisabled()
    const switchButton = screen.getByTitle('切换导航到该点')
    expect(switchButton).toBeEnabled()

    await user.click(switchButton)
    expect(onGoTo).toHaveBeenCalledWith('wp_002')
  })
})
