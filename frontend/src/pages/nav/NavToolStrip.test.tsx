import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { NavToolStrip } from './NavToolStrip'

function renderToolStrip(overrides: Partial<React.ComponentProps<typeof NavToolStrip>> = {}) {
  render(<NavToolStrip {...createToolStripProps(overrides)} />)
}

describe('NavToolStrip task controls', () => {
  it('uses a mapping icon before mapping and a save icon while mapping', () => {
    const { rerender } = render(<NavToolStrip {...createToolStripProps()} />)

    const startButton = screen.getByRole('button', { name: '开始建图' })
    expect(startButton.querySelector('.lucide-map-plus')).toBeInTheDocument()

    rerender(<NavToolStrip {...createToolStripProps({ mappingActive: true })} />)
    const finishButton = screen.getByRole('button', { name: '结束建图' })
    expect(finishButton).toHaveClass('is-active')
    expect(finishButton.querySelector('.lucide-save')).toBeInTheDocument()
  })

  it('shows a clear danger control only when a task is selected', () => {
    renderToolStrip()
    const disabledStopButton = screen.getByRole('button', { name: '停止任务' })
    expect(disabledStopButton).toBeDisabled()
    expect(disabledStopButton.querySelector('.lucide-circle-stop')).toBeInTheDocument()
  })

  it('locks mapping controls and shows progress during radar preflight', () => {
    renderToolStrip({ mappingPreflightChecking: true })
    const mappingButton = screen.getByRole('button', { name: '检查雷达中' })
    expect(mappingButton).toBeDisabled()
    expect(mappingButton.querySelector('.lucide-loader-circle')).toBeInTheDocument()
  })

  it('switches the rosbag control between start and stop states', () => {
    const { rerender } = render(<NavToolStrip {...createToolStripProps()} />)
    expect(screen.getByRole('button', { name: '开始录包' })).toBeEnabled()

    rerender(<NavToolStrip {...createToolStripProps({
      mappingActive: true,
      rosbagRunning: true,
      rosbagUsesMappingLidar: true,
    })} />)
    const stopButton = screen.getByRole('button', { name: '停止录包' })
    expect(stopButton).toHaveClass('is-active')
    expect(stopButton).toHaveAttribute('title', expect.stringContaining('复用建图中的雷达驱动'))
  })
})

function createToolStripProps(
  overrides: Partial<React.ComponentProps<typeof NavToolStrip>> = {},
): React.ComponentProps<typeof NavToolStrip> {
  return {
    canOperate: true,
    currentCmd: null,
    followRobot: false,
    isControlling: false,
    keyboardControlEnabled: false,
    lastResultText: null,
    linearSpeed: 0.4,
    mappingActive: false,
    mappingPreflightChecking: false,
    mappingSaving: false,
    mappingSending: false,
    mappingSessionInfo: null,
    navAutoTrackEnabled: false,
    navAutoTrackLoading: false,
    pcdLayerPanelOpen: false,
    pcdLayerVisibility: { map: true, ground: true, footprint: true },
    pointCloudQualityMode: 'auto',
    radarChecking: false,
    rosbagLoading: false,
    rosbagRunning: false,
    rosbagUsesMappingLidar: false,
    resultMessage: null,
    robotPoseAvailable: true,
    selectedSceneNavigable: true,
    selectedTaskId: null,
    toolMode: 'none',
    turnSpeed: 0.6,
    webglSupported: true,
    wallColorMode: 'solid',
    onCheckRadar: vi.fn(),
    onToggleRosbag: vi.fn(),
    onStopSelectedTask: vi.fn(),
    onToggleFollowRobot: vi.fn(),
    onToggleKeyboardControl: vi.fn(),
    onToggleLayer: vi.fn(),
    onToggleLayerPanel: vi.fn(),
    onSelectWallColorMode: vi.fn(),
    onSelectPointCloudQualityMode: vi.fn(),
    onToggleMapping: vi.fn(),
    onToggleNavAutoTrack: vi.fn(),
    onToolMode: vi.fn(),
    ...overrides,
  }
}
