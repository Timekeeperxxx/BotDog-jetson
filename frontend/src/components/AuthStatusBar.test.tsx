import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { AuthStatusBar } from './AuthStatusBar'
import { clearAuthState, setAuthState } from '../stores/authStore'

afterEach(() => {
  act(() => {
    clearAuthState()
  })
})

describe('AuthStatusBar', () => {
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
