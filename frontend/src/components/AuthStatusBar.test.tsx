import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { AuthStatusBar } from './AuthStatusBar'
import { clearAuthState, getAuthState, setAuthState } from '../stores/authStore'

afterEach(() => {
  vi.restoreAllMocks()
  act(() => {
    clearAuthState()
  })
})

describe('AuthStatusBar', () => {
  function signedIn() {
    act(() => setAuthState({ accessToken: 'token-1', id: 1, username: 'admin', role: 'admin', must_change_password: false }))
  }

  it('clears the browser session before clearing local login state', async () => {
    signedIn()
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('{"ack_cmd":"stop","result":"ACCEPTED","latency_ms":1}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    const onLogout = vi.fn()
    render(<AuthStatusBar onLogout={onLogout} />)
    await userEvent.click(screen.getByTitle('退出登录'))
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      expect.stringContaining('/api/v1/control/stop'),
      expect.stringContaining('/api/v1/auth/logout'),
    ])
    expect(getAuthState().accessToken).toBeNull()
    expect(onLogout).toHaveBeenCalledOnce()
  })

  it('shows a failed logout and keeps the session available for retry', async () => {
    signedIn()
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('{"ack_cmd":"stop","result":"ACCEPTED","latency_ms":1}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockRejectedValueOnce(new Error('offline'))
    const onLogout = vi.fn()
    render(<AuthStatusBar onLogout={onLogout} />)
    await userEvent.click(screen.getByTitle('退出登录'))
    expect(await screen.findByRole('alert')).toHaveTextContent('退出失败，请检查连接后重试')
    expect(getAuthState().accessToken).toBe('token-1')
    expect(onLogout).not.toHaveBeenCalled()
    expect(screen.getByTitle('退出登录')).toBeEnabled()
  })

  it('forces the change password modal when must_change_password is true', () => {
    act(() => {
      setAuthState({
        accessToken: 'token-1',
        id: 1,
        username: 'admin',
        role: 'admin',
        must_change_password: true,
      })
    })

    render(<AuthStatusBar variant="overlay" />)

    expect(screen.getByText('您的密码已被标记为必须修改，请设置新密码')).toBeInTheDocument()
    expect(screen.getByText('确认修改')).toBeInTheDocument()
    expect(screen.queryByText('取消')).not.toBeInTheDocument()
  })
})
