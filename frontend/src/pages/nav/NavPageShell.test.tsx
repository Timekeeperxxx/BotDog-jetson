import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { NavRightRail } from './NavPageShell'

vi.mock('../../components/pcd/PointCloudTopDownCanvas', () => ({
  PointCloudTopDownCanvas: () => <div data-testid="top-down-canvas" />,
}))
vi.mock('../../components/pcd/NavWaypointPanel', () => ({
  NavWaypointPanel: () => <div data-testid="waypoint-panel" />,
}))
vi.mock('../../components/pcd/NavFencePanel', () => ({
  NavFencePanel: () => <div data-testid="fence-panel" />,
}))

function renderRail(overrides: Partial<React.ComponentProps<typeof NavRightRail>> = {}) {
  const props: React.ComponentProps<typeof NavRightRail> = {
    bounds: null,
    canOperate: true,
    localizationStopSending: false,
    softStopSending: false,
    executionPath: null,
    globalPath: null,
    layers: [],
    goToSending: false,
    navigatingWaypointId: null,
    robotPose: null,
    sceneNavigable: true,
    viewKey: 'test',
    waypoints: [],
    fences: [],
    fencesVisible: true,
    onAddWaypoint: vi.fn(),
    onDeleteWaypoint: vi.fn(),
    onSoftStop: vi.fn(),
    onStopLocalization: vi.fn(),
    onGoToWaypoint: vi.fn(),
    onMouseMapPositionChange: vi.fn(),
    onSetPose: vi.fn(),
    onToggleFencesVisible: vi.fn(),
    onToggleFenceEnabled: vi.fn(),
    onDeleteFence: vi.fn(),
    ...overrides,
  }
  render(<NavRightRail {...props} />)
  return props
}

describe('NavRightRail stop controls', () => {
  it('separates navigation soft stop from stopping TF localization', () => {
    const props = renderRail()

    fireEvent.click(screen.getByRole('button', { name: '导航软停' }))
    fireEvent.click(screen.getByRole('button', { name: '停止导航和TF定位' }))

    expect(props.onSoftStop).toHaveBeenCalledTimes(1)
    expect(props.onStopLocalization).toHaveBeenCalledTimes(1)
  })

  it('locks both controls while the localization shutdown is running', () => {
    renderRail({ localizationStopSending: true })

    expect(screen.getByRole('button', { name: '导航软停' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '正在停止...' })).toBeDisabled()
  })
})
