import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AdminLogsPage } from './AdminLogsPage'

const adminApiMock = vi.hoisted(() => ({
  listLogFiles: vi.fn(),
  getLogFileTail: vi.fn(),
}))

vi.mock('../adminApi', () => adminApiMock)

afterEach(() => {
  vi.clearAllMocks()
})

describe('AdminLogsPage', () => {
  it('groups runtime logs and switches the selected file with the category', async () => {
    adminApiMock.listLogFiles.mockResolvedValue({
      items: [
        { name: 'backend.log', category: 'backend', size_bytes: 1024, modified_at: '2026-07-16T03:00:00Z', lines_hint: 10 },
        { name: 'ffmpeg.log', category: 'video', size_bytes: 2048, modified_at: '2026-07-16T03:01:00Z', lines_hint: 20 },
        { name: 'ros/navigation_1/launch.log', category: 'navigation', size_bytes: 512, modified_at: '2026-07-16T03:02:00Z', lines_hint: 5 },
      ],
    })
    adminApiMock.getLogFileTail.mockImplementation((name: string) => Promise.resolve({
      name,
      lines: [`${name} output`],
      line_count: 1,
      truncated: false,
    }))

    const user = userEvent.setup()
    render(
      <AdminLogsPage
        logs={[]}
        loading={false}
        search=""
        onSearchChange={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: '运行日志' }))
    await waitFor(() => expect(adminApiMock.getLogFileTail).toHaveBeenCalledWith('backend.log', 300))

    await user.click(screen.getByRole('button', { name: /视频系统/ }))
    await waitFor(() => expect(adminApiMock.getLogFileTail).toHaveBeenLastCalledWith('ffmpeg.log', 300))
    expect(screen.getByRole('combobox')).toHaveValue('ffmpeg.log')
    expect(screen.getByText('ffmpeg.log output')).toBeInTheDocument()
  })
})
