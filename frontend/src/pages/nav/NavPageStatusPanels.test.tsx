import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { NavMessageCenter, SceneInfoDrawer } from './NavPageStatusPanels'

describe('NavMessageCenter', () => {
  it('promotes errors and renders structured readable log rows', () => {
    render(
      <NavMessageCenter
        notice={{ title: '操作异常', message: '雷达未连接，无法开始建图' }}
        noticeKind="error"
        logs={[
          {
            id: 1,
            level: 'error',
            timestamp: new Date('2026-07-18T14:21:30').getTime(),
            message: '雷达未连接，无法开始建图',
          },
          {
            id: 2,
            level: 'info',
            timestamp: new Date('2026-07-18T14:20:00').getTime(),
            message: '系统启动检查开始',
          },
        ]}
        expanded
        onToggleExpanded={vi.fn()}
      />,
    )

    const messageCenter = screen.getByText('操作异常').closest('section')
    expect(messageCenter).toHaveClass('is-error', 'is-log-expanded')
    expect(messageCenter).toHaveAttribute('aria-live', 'assertive')
    expect(messageCenter?.querySelector('.lucide-triangle-alert')).toBeInTheDocument()

    const log = screen.getByRole('log', { name: '导航历史日志' })
    expect(log.querySelectorAll('.pcd-message-log-row')).toHaveLength(2)
    expect(screen.getAllByText('错误').length).toBeGreaterThan(0)
    expect(screen.getByText('最多保留 30 条', { exact: false })).toBeInTheDocument()
  })
})


it('shows the orbit centre in map metres and updates or clears its readout', () => {
  const props = {
    open: true, metadata: null, sceneDisplayPointCount: null,
    mouseMapPosition: { x: 99, y: 88 }, robotPose: null,
    selectedSceneReady: false, selectedSceneNavigable: false,
    selectedSceneMessage: null, localizationStatus: null, onToggle: vi.fn(),
  }
  const { rerender } = render(
    <SceneInfoDrawer {...props} viewCenterPosition={{ x: 12.3456, y: -4.5678 }} />,
  )
  expect(screen.getByText('视图中心 X/Y（m）').nextElementSibling).toHaveTextContent('12.346, -4.568')
  rerender(<SceneInfoDrawer {...props} viewCenterPosition={{ x: 3, y: 2 }} />)
  expect(screen.getByText('视图中心 X/Y（m）').nextElementSibling).toHaveTextContent('3.000, 2.000')
  rerender(<SceneInfoDrawer {...props} viewCenterPosition={null} />)
  expect(screen.getByText('视图中心 X/Y（m）').nextElementSibling).toHaveTextContent('-')
})

it('uses the compact save row in the existing message bar and keeps the log control', () => {
  render(
    <NavMessageCenter
      notice={{ title: '后台正在保存', message: '重复说明不应另外占一块' }}
      noticeKind="waiting"
      mappingSaving
      mappingSaveStatus={{
        success: true, enabled: false, running: false, saving: true, saved: false,
        scene_name: 'Scene1', map_dir: '/maps/Scene1', pid: 1,
        map_pcd_candidates: [], ground_pcd_candidates: [], pcd_files: [], message: null,
        save_elapsed_seconds: 100, save_progress: {
          stage: 'loop_optimize', label: '回环与轨迹优化', detail: '',
          completed: null, total: null, baseline_saved: false,
        },
      }}
      logs={[]}
      expanded={false}
      onToggleExpanded={vi.fn()}
    />,
  )
  expect(screen.getByRole('region', { name: '地图保存进度' })).toBeInTheDocument()
  expect(screen.queryByText('重复说明不应另外占一块')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /历史日志/ })).toBeInTheDocument()
})

it('removes the save row and returns to the normal completion notice after saving', () => {
  const props = { logs: [], expanded: false, onToggleExpanded: vi.fn() }
  const { rerender } = render(<NavMessageCenter {...props} notice={null} noticeKind="waiting" mappingSaving />)
  expect(screen.getByRole('region', { name: '地图保存进度' })).toBeInTheDocument()
  rerender(<NavMessageCenter {...props} notice={{ title: '地图保存完成', message: '可查看场景' }} noticeKind="ready" mappingSaving={false} />)
  expect(screen.queryByRole('region', { name: '地图保存进度' })).not.toBeInTheDocument()
  expect(screen.getByText('地图保存完成')).toBeInTheDocument()
})
