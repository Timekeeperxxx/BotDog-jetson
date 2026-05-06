import { afterEach, describe, expect, it, vi } from 'vitest'

type StoredAuthState = {
  accessToken: string
  username: string
  role: 'viewer' | 'operator' | 'admin'
}

type LoadStoreOptions = {
  fetchImpl?: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
  storedState?: StoredAuthState
  pathname?: string
}

function installLocalStorageMock() {
  const storage = new Map<string, string>()
  const localStorageMock = {
    getItem: vi.fn((key: string) => storage.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      storage.set(key, value)
    }),
    removeItem: vi.fn((key: string) => {
      storage.delete(key)
    }),
    clear: vi.fn(() => {
      storage.clear()
    }),
  }

  Object.defineProperty(window, 'localStorage', {
    value: localStorageMock,
    configurable: true,
  })

  return localStorageMock
}

async function loadStore(options: LoadStoreOptions = {}) {
  vi.resetModules()
  const localStorageMock = installLocalStorageMock()
  localStorageMock.clear()
  window.history.replaceState({}, '', options.pathname ?? '/')

  if (options.storedState) {
    window.localStorage.setItem('botdog-auth', JSON.stringify(options.storedState))
  }

  const mockFetch = vi.fn(
    options.fetchImpl ??
      (async () =>
        new Response('{}', {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })),
  )

  vi.stubGlobal('fetch', mockFetch)
  window.fetch = mockFetch as unknown as typeof fetch

  const store = await import('./authStore')
  return { ...store, localStorageMock, mockFetch }
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.history.replaceState({}, '', '/')
})

describe('authStore', () => {
  it('injects Authorization only for API requests', async () => {
    const { installAuthFetchInterceptor, setAuthState, mockFetch } = await loadStore()

    installAuthFetchInterceptor()
    setAuthState({
      accessToken: 'token-123',
      id: 1,
      username: 'admin',
      role: 'admin',
      must_change_password: false,
    })

    await window.fetch('http://localhost/api/v1/control/command', { method: 'POST' })
    await window.fetch('http://localhost/assets/app.js')

    const apiRequest = mockFetch.mock.calls[0][0] as Request
    const assetRequest = mockFetch.mock.calls[1][0] as Request

    expect(apiRequest.headers.get('Authorization')).toBe('Bearer token-123')
    expect(assetRequest.headers.get('Authorization')).toBeNull()
  })

  it('clears auth state and redirects to login on API 401', async () => {
    const { getAuthState, installAuthFetchInterceptor, setAuthState } = await loadStore({
      fetchImpl: async () =>
        new Response(JSON.stringify({ detail: '缺少访问令牌' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
    })

    installAuthFetchInterceptor()
    setAuthState({
      accessToken: 'expired-token',
      id: 1,
      username: 'admin',
      role: 'admin',
      must_change_password: false,
    })

    await window.fetch('http://localhost/api/v1/control/command', { method: 'POST' })

    expect(getAuthState().accessToken).toBeNull()
    expect(getAuthState().username).toBeNull()
    expect(getAuthState().role).toBeNull()
  })

  it('bootstraps auth bypass when backend auth is disabled', async () => {
    const { bootstrapAuthState, getAuthState } = await loadStore({
      fetchImpl: async () =>
        new Response(JSON.stringify({ username: 'dev', role: 'admin' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    })

    await bootstrapAuthState()

    expect(getAuthState()).toMatchObject({
      accessToken: null,
      username: 'dev',
      role: 'admin',
      authBypass: true,
      ready: true,
      validating: false,
    })
  })

  it('clears stored token when startup validation fails', async () => {
    const { bootstrapAuthState, getAuthState } = await loadStore({
      storedState: {
        accessToken: 'stale-token',
        username: 'admin',
        role: 'admin',
      },
      fetchImpl: async () =>
        new Response(JSON.stringify({ detail: 'token 已过期' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
    })

    await bootstrapAuthState()

    expect(getAuthState()).toMatchObject({
      accessToken: null,
      username: null,
      role: null,
      authBypass: false,
      ready: true,
      validating: false,
    })
    expect(window.localStorage.getItem('botdog-auth')).toBeNull()
  })
})
