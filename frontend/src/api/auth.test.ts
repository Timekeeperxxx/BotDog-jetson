import { describe, expect, it, vi } from 'vitest'

const apiFetchMock = vi.hoisted(() => vi.fn())

vi.mock('./apiFetch', () => ({
  apiFetch: apiFetchMock,
}))

describe('auth api', () => {
  it('uses apiFetch for current user and auth status requests', async () => {
    apiFetchMock.mockResolvedValueOnce({
      id: 1,
      username: 'admin',
      role: 'admin',
      must_change_password: false,
    })
    apiFetchMock.mockResolvedValueOnce({
      auth_enabled: true,
      current_user: {
        id: 1,
        username: 'admin',
        role: 'admin',
        must_change_password: false,
      },
    })

    const { getCurrentUser, getAuthStatus } = await import('./auth')

    await expect(getCurrentUser()).resolves.toEqual({
      id: 1,
      username: 'admin',
      role: 'admin',
      must_change_password: false,
    })
    await expect(getAuthStatus()).resolves.toEqual({
      auth_enabled: true,
      current_user: {
        id: 1,
        username: 'admin',
        role: 'admin',
        must_change_password: false,
      },
    })

    expect(apiFetchMock).toHaveBeenNthCalledWith(1, '/api/v1/auth/me')
    expect(apiFetchMock).toHaveBeenNthCalledWith(2, '/api/v1/auth/status')
  })
})
