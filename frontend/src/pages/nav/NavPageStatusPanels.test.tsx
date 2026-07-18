import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { NavMessageCenter } from './NavPageStatusPanels'

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
