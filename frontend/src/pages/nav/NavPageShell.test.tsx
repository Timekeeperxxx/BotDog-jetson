import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { NavRightRail } from './NavPageShell'

vi.mock('../../components/pcd/PointCloudTopDownCanvas', () => ({
  PointCloudTopDownCanvas: () => <div>2D 俯视投影</div>,
}))
vi.mock('../../stores/authStore', () => ({
  hasAuthSession: () => true,
  hasRole: () => true,
  useAuthState: vi.fn(),
}))

function props() {
  return {
    bounds: null, canOperate: true, estopSending: false, executionPath: null,
    globalPath: null, layers: [], goToSending: false, navigatingWaypointId: null,
    robotPose: null, sceneNavigable: true, viewKey: 'scene', fencesVisible: true,
    waypoints: [{ id: 'wp1', map_id: 'scene', name: '巡检点1', x: 1, y: 2, z: 0,
      yaw: 0, frame_id: 'map', created_at: '', updated_at: '' }],
    fences: [{ id: 'f1', scene_id: 'scene', start: { x: 0, y: 0 }, end: { x: 2, y: 0 }, enabled: true }],
    onAddWaypoint: vi.fn(), onDeleteWaypoint: vi.fn(), onEmergencyStop: vi.fn(),
    onGoToWaypoint: vi.fn(), onMouseMapPositionChange: vi.fn(), onSetPose: vi.fn(),
    onToggleFencesVisible: vi.fn(), onToggleFenceEnabled: vi.fn(), onDeleteFence: vi.fn(),
  }
}

describe('NavRightRail', () => {
  it('shares one list area and preserves actions and emergency stop across keyboard tab changes', async () => {
    const user = userEvent.setup()
    const callbacks = props()
    render(<NavRightRail {...callbacks} />)
    const waypointsTab = screen.getByRole('tab', { name: '导航点 1' })
    const fencesTab = screen.getByRole('tab', { name: '围栏 1' })
    expect(waypointsTab).toHaveAttribute('aria-selected', 'true')
    await user.click(screen.getByTitle('导航到该点'))
    expect(callbacks.onGoToWaypoint).toHaveBeenCalledWith('wp1')

    waypointsTab.focus()
    await user.keyboard('{ArrowRight}')
    expect(fencesTab).toHaveFocus()
    expect(fencesTab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getAllByRole('tabpanel')).toHaveLength(1)
    expect(within(screen.getByRole('tabpanel')).queryByText('巡检点1')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '已启用' }))
    expect(callbacks.onToggleFenceEnabled).toHaveBeenCalledWith('f1', false)
    await user.click(screen.getByTitle('隐藏围栏'))
    expect(callbacks.onToggleFencesVisible).toHaveBeenCalledOnce()
    await user.click(screen.getByRole('button', { name: '导航急停' }))
    expect(callbacks.onEmergencyStop).toHaveBeenCalledOnce()

    fencesTab.focus()
    await user.keyboard('{Home}')
    expect(waypointsTab).toHaveFocus()
    expect(screen.getByText('巡检点1')).toBeInTheDocument()
  })

  it('shows an empty hint only in the selected list and keeps the stop permission gate', async () => {
    const user = userEvent.setup()
    render(<NavRightRail {...props()} fences={[]} canOperate={false} />)
    await user.click(screen.getByRole('tab', { name: '围栏 0' }))
    expect(screen.getByText('点击“添加围栏”，在地面依次选择起点和终点')).toBeInTheDocument()
    expect(screen.queryByText('巡检点1')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '导航急停' })).toBeDisabled()
  })
})
