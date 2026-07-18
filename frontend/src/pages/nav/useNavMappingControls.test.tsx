import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useNavMappingControls } from './useNavMappingControls'

const pcdMapApiMock = vi.hoisted(() => ({
  checkRadarPreflight: vi.fn(),
  getMappingStatus: vi.fn(),
  setMappingEnabled: vi.fn(),
}))

vi.mock('../../api/pcdMapApi', () => pcdMapApiMock)

const addLogMock = vi.fn()
const refreshScenesMock = vi.fn(async () => {})

function MappingControlsHarness() {
  const controls = useNavMappingControls({
    addLog: addLogMock,
    canOperate: true,
    refreshScenes: refreshScenesMock,
  })

  return (
    <div>
      <span data-testid="mapping-active">{String(controls.mappingActive)}</span>
      <span data-testid="mapping-saving">{String(controls.mappingSaving)}</span>
      <span data-testid="mapping-dialog-open">{String(controls.mappingDialogOpen)}</span>
      <span data-testid="mapping-error">{controls.mappingSceneError || ''}</span>
      <input
        aria-label="scene name"
        value={controls.mappingSceneName}
        onChange={(event) => controls.setMappingSceneName(event.target.value)}
      />
      <button type="button" onClick={controls.handleToggleMapping}>toggle mapping</button>
      <button type="button" onClick={() => void controls.handleConfirmStartMapping()}>confirm mapping</button>
    </div>
  )
}

describe('useNavMappingControls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    pcdMapApiMock.getMappingStatus.mockResolvedValue({
      success: true,
      enabled: false,
      running: false,
      saving: false,
      saved: false,
      scene_name: null,
      map_dir: null,
      pid: null,
      map_pcd_candidates: [],
      ground_pcd_candidates: [],
      pcd_files: [],
      message: null,
    })
  })

  it('leaves frontend mapping mode immediately while the backend is still saving', async () => {
    pcdMapApiMock.getMappingStatus.mockResolvedValueOnce({
      success: true,
      enabled: true,
      running: true,
      saving: false,
      saved: false,
      scene_name: 'Scene26_hqzx',
      map_dir: '/maps/Scene26_hqzx',
      pid: 123,
      started_at: Date.now() / 1000 - 120,
      map_pcd_candidates: [],
      ground_pcd_candidates: [],
      pcd_files: [],
      message: '建图正在运行',
    }).mockResolvedValueOnce({
      success: true,
      enabled: false,
      running: false,
      saving: false,
      saved: true,
      scene_name: 'Scene26_hqzx',
      map_dir: '/maps/Scene26_hqzx',
      pid: 123,
      started_at: Date.now() / 1000 - 120,
      map_pcd_candidates: ['map.pcd'],
      ground_pcd_candidates: ['terrain_map_test_ground.pcd'],
      pcd_files: [],
      message: '地图已保存',
    })
    pcdMapApiMock.setMappingEnabled.mockResolvedValue({
      success: true,
      enabled: false,
      running: false,
      saving: true,
      saved: false,
      scene_name: 'Scene26_hqzx',
      map_dir: '/maps/Scene26_hqzx',
      pid: 123,
      map_pcd_candidates: [],
      ground_pcd_candidates: [],
      pcd_files: [],
      message: '建图已停止，地图正在后台保存',
    })

    render(<MappingControlsHarness />)

    await waitFor(() => {
      expect(screen.getByTestId('mapping-active')).toHaveTextContent('true')
    })

    fireEvent.click(screen.getByRole('button', { name: 'toggle mapping' }))

    await waitFor(() => {
      expect(screen.getByTestId('mapping-active')).toHaveTextContent('false')
      expect(screen.getByTestId('mapping-saving')).toHaveTextContent('true')
    })
    expect(pcdMapApiMock.setMappingEnabled).toHaveBeenCalledWith(false)

    await waitFor(() => {
      expect(screen.getByTestId('mapping-saving')).toHaveTextContent('false')
    }, { timeout: 2000 })
    expect(pcdMapApiMock.getMappingStatus).toHaveBeenCalledTimes(2)
  })

  it('blocks mapping and shows a clear error when radar preflight fails', async () => {
    pcdMapApiMock.checkRadarPreflight.mockResolvedValue({
      ok: false,
      level: 'error',
      topic: null,
      topic_type: null,
      publisher_count: null,
      subscription_count: null,
      frequency_hz: null,
      checked_at: '2026-07-18T00:00:00.000Z',
      checks: [],
      message: '雷达未连接：未发现原始数据 /livox/lidar',
    })

    render(<MappingControlsHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'toggle mapping' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'scene name' }), {
      target: { value: '实验室' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'confirm mapping' }))

    await waitFor(() => {
      expect(screen.getByTestId('mapping-error')).toHaveTextContent('雷达未连接')
    })
    expect(screen.getByTestId('mapping-dialog-open')).toHaveTextContent('true')
    expect(pcdMapApiMock.setMappingEnabled).not.toHaveBeenCalled()
    expect(addLogMock).toHaveBeenCalledWith(
      expect.stringContaining('建图未启动：雷达未连接'),
      'error',
    )
  })

  it('keeps the dialog open when the backend rejects a radar disconnect race', async () => {
    pcdMapApiMock.checkRadarPreflight.mockResolvedValue({
      ok: true,
      level: 'normal',
      topic: '/livox/lidar',
      topic_type: 'livox_ros_driver2/msg/CustomMsg',
      publisher_count: 1,
      subscription_count: 1,
      frequency_hz: 10,
      checked_at: '2026-07-18T00:00:00.000Z',
      checks: [],
      message: '雷达连接正常',
    })
    pcdMapApiMock.setMappingEnabled.mockRejectedValue(
      new Error('建图未启动：雷达无有效数据，请检查雷达连接'),
    )

    render(<MappingControlsHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'toggle mapping' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'scene name' }), {
      target: { value: '实验室' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'confirm mapping' }))

    await waitFor(() => {
      expect(screen.getByTestId('mapping-error')).toHaveTextContent('雷达无有效数据')
    })
    expect(screen.getByTestId('mapping-dialog-open')).toHaveTextContent('true')
    expect(screen.getByTestId('mapping-active')).toHaveTextContent('false')
    expect(pcdMapApiMock.setMappingEnabled).toHaveBeenCalledWith(true, '实验室')
  })
})
