import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { MapLoadingProgress } from './MapLoadingProgress'
import { parseMapLoadingDetail } from './mapLoadingProgress'
import { NavPageHeader } from './NavPageShell'

afterEach(cleanup)

describe('MapLoadingProgress', () => {
  it('shows the real per-file count from the backend, not scene progress', () => {
    render(<MapLoadingProgress loading message="整理 map.pcd：482,517 / 1,434,248 点" />)
    expect(screen.getByText('整理点云')).toBeInTheDocument()
    expect(screen.getByText('map.pcd')).toBeInTheDocument()
    expect(screen.getByText('当前文件')).toBeInTheDocument()
    expect(screen.getByText('33.6%')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '482517')
    expect(screen.getByRole('progressbar')).toHaveAttribute('max', '1434248')
    expect(screen.getByText('482,517 / 1,434,248 点')).toBeInTheDocument()
  })
  it('does not invent a total for reading', () => {
    render(<MapLoadingProgress loading message="读取 ground.pcd：131,072 点" />)
    expect(screen.getByText('读取点云')).toBeInTheDocument()
    expect(screen.getByText('已读取 131,072 点')).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })
  it('shows preparation before the first polling response', () => {
    render(<MapLoadingProgress loading message="" />)
    expect(screen.getByText('正在获取地图数据')).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })
  it('keeps unknown or error text without pretending it is determinate', () => {
    render(<MapLoadingProgress loading message="连接暂时中断，正在重试" />)
    expect(screen.getByText('连接暂时中断，正在重试')).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })
  it('disappears after success or failure, even with a stale message', () => {
    const { rerender } = render(<MapLoadingProgress loading message="读取 map.pcd：12 点" />)
    rerender(<MapLoadingProgress loading={false} message="读取 map.pcd：12 点" />)
    expect(screen.queryByLabelText('地图加载进度')).not.toBeInTheDocument()
  })
  it('100% only means this file is ready, not that scene loading finished', () => {
    render(<MapLoadingProgress loading message="整理 footprint_fill.pcd: 4 / 4 点" />)
    expect(screen.getByText('100%')).toBeInTheDocument()
    expect(screen.getByText('当前文件已整理，正在完成地图加载')).toBeInTheDocument()
    expect(screen.getByLabelText('地图加载进度')).toHaveAttribute('aria-busy', 'true')
  })
  it('replaces the previous file and resets its counts', () => {
    const { rerender } = render(<MapLoadingProgress loading message="整理 map.pcd：90 / 100 点" />)
    rerender(<MapLoadingProgress loading message="读取 新场景_ground.pcd：12 点" />)
    expect(screen.queryByText('map.pcd')).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.getByText('新场景_ground.pcd')).toBeInTheDocument()
  })
  it('keeps long filenames available and renders markup as plain text', () => {
    const filename = '<img src=x onerror=alert(1)>' + '地下楼层_'.repeat(40) + '.pcd'
    render(<MapLoadingProgress loading message={`整理 ${filename}：0 / 123 点`} />)
    expect(screen.getByTitle(filename)).toHaveTextContent(filename)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '0')
  })
  it.each(['整理 map.pcd：2 / 0 点', '整理 map.pcd：11 / 10 点',
    '整理 map.pcd：-1 / 10 点', '整理 map.pcd：1,,2 / 10 点',
    '整理 map.pcd：9007199254740993 / 9007199254740994 点'])('rejects invalid counts: %s', (message) => {
    expect(parseMapLoadingDetail(message).total).toBeNull()
  })
})

describe('NavPageHeader loading isolation', () => {
  const props = { addMode: false, batteryPct: 67, canOperate: true, loading: false,
    restartLocalizationSending: false, selectedSceneNavigable: true, webglSupported: true,
    previewAvailable: true, onRestartLocalization: () => {}, onToggleWaypointMode: () => {} }
  it('reserves a short state outside the battery/actions group across loading transitions', () => {
    const { container, rerender } = render(<NavPageHeader {...props} />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(container.querySelector('.pcd-title-row .pcd-loading')).toHaveClass('is-idle')
    rerender(<NavPageHeader {...props} loading />)
    expect(screen.getByRole('status')).toHaveTextContent('加载中')
    expect(container.querySelector('.pcd-header-actions .pcd-loading')).toBeNull()
    expect(screen.getByTitle('机器狗剩余电量')).toHaveTextContent('67%')
    expect(screen.getByRole('button', { name: '重启导航定位' })).toBeEnabled()
    rerender(<NavPageHeader {...props} />)
    expect(screen.getByTitle('机器狗剩余电量')).toHaveTextContent('67%')
  })
})
