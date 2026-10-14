import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MappingControlResponse } from '../../types/pcdMap'
import { formatSaveTime, MappingSaveProgress } from './MappingSaveProgress'

const base: MappingControlResponse = {
  success: true, enabled: false, running: false, saving: true, saved: false,
  scene_name: 'Scene1_一楼', map_dir: '/maps/Scene1_一楼', pid: 1,
  map_pcd_candidates: [], ground_pcd_candidates: [], pcd_files: [], message: null,
  save_elapsed_seconds: 58, save_worker_alive: true,
  save_progress: { stage: 'loop_map', label: '重建回环地图', detail: '按最终轨迹重建点云',
    completed: 64, total: 480, unit: '关键帧', baseline_saved: false,
    stage_elapsed_seconds: 10, update_age_seconds: 1 },
}

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks() })

describe('MappingSaveProgress', () => {
  it('keeps stage, truthful counts and elapsed time in the collapsed status row', () => {
    render(<MappingSaveProgress status={base} connectionError={null} />)
    expect(screen.getByText('重建回环地图')).toBeInTheDocument()
    expect(screen.getByLabelText('当前阶段关键帧：64 / 480')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('max', '480')
    expect(screen.getByLabelText('保存已用 0分58秒')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByText(/完成前请勿关闭设备/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看保存详情' }))
    const details = screen.getByRole('dialog', { name: '地图保存详情' })
    expect(within(details).getByText('Scene1_一楼')).toBeInTheDocument()
    expect(within(details).getByText(/完成前请勿关闭设备或使用该场景导航/)).toBeInTheDocument()
  })

  it('never invents a percentage when there is no trustworthy total', () => {
    render(<MappingSaveProgress status={{ ...base, save_progress: {
      ...base.save_progress!, completed: null, total: null, label: '回环与轨迹优化',
    } }} connectionError={null} />)
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.getByText('回环与轨迹优化')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看保存详情' }))
    expect(screen.getByText(/不估算完成百分比/)).toBeInTheDocument()
  })

  it('keeps the last phase visible and exposes reconnection in the collapsed row', () => {
    render(<MappingSaveProgress status={base} connectionError="暂时无法获取保存进度，正在自动重连" />)
    expect(screen.getByText('重建回环地图')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('正在重连')
    fireEvent.click(screen.getByRole('button', { name: '查看保存详情' }))
    expect(screen.queryByText('保存进程仍在运行')).not.toBeInTheDocument()
    expect(screen.getByText('暂时无法获取保存进度，正在自动重连')).toBeInTheDocument()
  })

  it('never treats written baseline files as a finished save', () => {
    render(<MappingSaveProgress status={{ ...base, save_progress: {
      ...base.save_progress!, baseline_saved: true,
    } }} connectionError={null} />)
    expect(screen.getByText('保存中')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看保存详情' }))
    expect(screen.getByText(/基础文件已写入，最终优化与验收尚未结束/)).toBeInTheDocument()
  })

  it('dismisses details with Escape and restores keyboard focus to the trigger', () => {
    render(<MappingSaveProgress status={base} connectionError={null} />)
    const trigger = screen.getByRole('button', { name: '查看保存详情' })
    fireEvent.click(trigger)
    expect(screen.getByRole('dialog')).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('dismisses the floating details on an outside pointer action', () => {
    render(<MappingSaveProgress status={base} connectionError={null} />)
    fireEvent.click(screen.getByRole('button', { name: '查看保存详情' }))
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows stale telemetry as a warning without claiming numerical progress or completion', () => {
    render(<MappingSaveProgress status={{ ...base, save_progress: {
      ...base.save_progress!, update_age_seconds: 70,
    } }} connectionError={null} />)
    expect(screen.getByRole('status')).toHaveTextContent('进度待更新')
    expect(screen.getByRole('progressbar').parentElement).toHaveAttribute('title', '上次记录的关键帧：64 / 480')
  })

  it('keeps unrelated operation errors visible while saving', () => {
    render(<MappingSaveProgress status={base} connectionError={null} operationError={{
      title: '操作异常', message: '停止导航请求失败',
    }} />)
    expect(screen.getByRole('alert')).toHaveTextContent('停止导航请求失败')
    expect(screen.getByText('重建回环地图')).toBeInTheDocument()
  })

  it('uses an accurate fallback for an active stage with an empty description', () => {
    render(<MappingSaveProgress status={{ ...base, save_progress: {
      ...base.save_progress!, detail: '',
    } }} connectionError={null} />)
    fireEvent.click(screen.getByRole('button', { name: '查看保存详情' }))
    expect(screen.getByText(/后台正在处理当前阶段/)).toBeInTheDocument()
    expect(screen.queryByText(/正在等待后台报告保存阶段/)).not.toBeInTheDocument()
  })

  it('continues elapsed time between responses using the client monotonic clock', () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'performance'] })
    render(<MappingSaveProgress status={base} connectionError={null} />)
    act(() => { vi.advanceTimersByTime(3000) })
    expect(screen.getByLabelText('保存已用 1分01秒')).toBeInTheDocument()
  })

  it('formats invalid or negative times safely', () => {
    expect(formatSaveTime(Number.NaN)).toBe('0分00秒')
    expect(formatSaveTime(-4)).toBe('0分00秒')
    expect(formatSaveTime(125)).toBe('2分05秒')
  })
})
