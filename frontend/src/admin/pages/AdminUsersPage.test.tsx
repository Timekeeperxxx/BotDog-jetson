import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AdminUsersPage } from './AdminUsersPage'
import { clearAuthState, setAuthState } from '../../stores/authStore'

const usersApiMock = vi.hoisted(() => ({
  listUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  deleteUser: vi.fn(),
  resetPassword: vi.fn(),
  changePassword: vi.fn(),
}))

vi.mock('../../api/usersApi', () => ({
  usersApi: usersApiMock,
}))

afterEach(() => {
  act(() => {
    clearAuthState()
  })
  vi.clearAllMocks()
})

describe('AdminUsersPage', () => {
  it('keeps create/edit and reset password errors separate', async () => {
    act(() => {
      setAuthState({
        accessToken: 'token-1',
        id: 1,
        username: 'admin',
        role: 'admin',
        must_change_password: false,
      })
    })

    usersApiMock.listUsers.mockResolvedValue([
      {
        id: 2,
        username: 'demo',
        role: 'viewer',
        enabled: true,
        must_change_password: false,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        last_login_at: null,
        deleted_at: null,
      },
    ])
    usersApiMock.createUser.mockRejectedValue(new Error('创建失败'))

    const user = userEvent.setup()
    render(<AdminUsersPage />)

    await waitFor(() => expect(screen.getByText('demo')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: '新增用户' }))
    await user.type(screen.getByPlaceholderText('登录名，不可包含特殊字符'), 'alice')
    await user.type(screen.getByPlaceholderText('至少 8 位字符'), 'Password123!')
    await user.type(screen.getByPlaceholderText('再次输入密码'), 'Password123!')
    await user.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(screen.getByText('创建失败')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: '取消' }))

    await user.click(screen.getByRole('button', { name: '重置密码' }))
    await user.type(screen.getByPlaceholderText('至少 8 位字符'), '123')
    await user.type(screen.getByPlaceholderText('再次输入密码'), '123')
    await user.click(screen.getByRole('button', { name: '确认重置' }))
    await waitFor(() => expect(screen.getByText('密码至少 8 位')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: '取消' }))

    await user.click(screen.getByRole('button', { name: '新增用户' }))
    await waitFor(() => expect(screen.queryByText('密码至少 8 位')).not.toBeInTheDocument())
    expect(screen.queryByText('用户名不能为空')).not.toBeInTheDocument()
  })
})
