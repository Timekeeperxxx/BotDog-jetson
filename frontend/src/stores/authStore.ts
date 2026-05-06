import { useSyncExternalStore } from 'react'
import { getCurrentUser } from '../api/auth'

type AuthRole = 'viewer' | 'operator' | 'admin' | null

type AuthState = {
  accessToken: string | null
  id: number | null
  username: string | null
  role: AuthRole
  must_change_password: boolean
  authBypass: boolean
  ready: boolean
  validating: boolean
  lastAuthError: string | null
}

const STORAGE_KEY = 'botdog-auth'
const listeners = new Set<() => void>()

const ROLE_LEVELS: Record<Exclude<AuthRole, null>, number> = {
  viewer: 1,
  operator: 2,
  admin: 3,
}

let fetchInterceptorInstalled = false
let authBootstrapPromise: Promise<void> | null = null

function getGuestState(): AuthState {
  return {
    accessToken: null,
    id: null,
    username: null,
    role: null,
    must_change_password: false,
    authBypass: false,
    ready: true,
    validating: false,
    lastAuthError: null,
  }
}

function readStoredState(): AuthState {
  if (typeof window === 'undefined') return getGuestState()

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return getGuestState()
    const data = JSON.parse(raw) as Partial<AuthState>
    return {
      accessToken: typeof data.accessToken === 'string' ? data.accessToken : null,
      id: typeof data.id === 'number' ? data.id : null,
      username: typeof data.username === 'string' ? data.username : null,
      role: data.role === 'viewer' || data.role === 'operator' || data.role === 'admin' ? data.role : null,
      must_change_password: typeof data.must_change_password === 'boolean' ? data.must_change_password : false,
      authBypass: false,
      ready: false,
      validating: false,
      lastAuthError: null,
    }
  } catch {
    return getGuestState()
  }
}

let authState: AuthState = readStoredState()

function emit() {
  listeners.forEach((listener) => listener())
}

function persistState(next: AuthState) {
  if (typeof window !== 'undefined') {
    if (next.accessToken) {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          accessToken: next.accessToken,
          id: next.id,
          username: next.username,
          role: next.role,
          must_change_password: next.must_change_password,
        }),
      )
    } else {
      window.localStorage.removeItem(STORAGE_KEY)
    }
  }
}

function writeState(next: AuthState) {
  authState = next
  persistState(next)
  emit()
}

function setTransientState(patch: Partial<AuthState>) {
  authState = { ...authState, ...patch }
  emit()
}

function isApiRequestUrl(input: RequestInfo | URL, request: Request): boolean {
  const rawUrl = typeof input === 'string' ? input : input instanceof URL ? input.toString() : request.url
  const base = typeof window !== 'undefined' ? window.location.origin : 'http://localhost'

  try {
    const parsed = new URL(rawUrl, base)
    return parsed.pathname.startsWith('/api/')
  } catch {
    return rawUrl.startsWith('/api/')
  }
}

function isAuthRoute(pathname: string): boolean {
  return pathname.startsWith('/api/v1/auth/')
}

function redirectToLogin() {
  if (window.location.pathname === '/login') return
  if (typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent)) {
    window.history.replaceState({}, '', '/login')
    return
  }
  try {
    window.location.assign('/login')
  } catch {
    window.history.replaceState({}, '', '/login')
  }
}

export function setAuthState(next: { accessToken: string; id: number; username: string; role: Exclude<AuthRole, null>; must_change_password: boolean }) {
  writeState({
    accessToken: next.accessToken,
    id: next.id,
    username: next.username,
    role: next.role,
    must_change_password: next.must_change_password,
    authBypass: false,
    ready: true,
    validating: false,
    lastAuthError: null,
  })
}

export function clearAuthState(reason?: string) {
  const next = getGuestState()
  if (reason) next.lastAuthError = reason
  writeState(next)
}

export function getAuthState() {
  return authState
}

export function hasRole(requiredRole: Exclude<AuthRole, null>) {
  if (!authState.role) return false
  return ROLE_LEVELS[authState.role] >= ROLE_LEVELS[requiredRole]
}

export function hasAuthSession() {
  return authState.authBypass || Boolean(authState.accessToken)
}

export function getLastAuthError(): string | null {
  return authState.lastAuthError
}

export function clearLastAuthError() {
  if (!authState.lastAuthError) return
  authState = { ...authState, lastAuthError: null }
  emit()
}

export function useAuthState() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => authState,
    () => authState,
  )
}

export async function bootstrapAuthState() {
  if (authBootstrapPromise) return authBootstrapPromise

  authBootstrapPromise = (async () => {
    if (typeof window === 'undefined') return

    const hasStoredToken = Boolean(authState.accessToken)
    if (!hasStoredToken && authState.ready) {
      setTransientState({ ready: false, validating: true })
    } else {
      setTransientState({ ready: false, validating: true })
    }

    try {
      const user = await getCurrentUser()
      writeState({
        accessToken: authState.accessToken,
        id: user.id,
        username: user.username,
        role: user.role,
        must_change_password: user.must_change_password,
        authBypass: !hasStoredToken,
        ready: true,
        validating: false,
        lastAuthError: null,
      })
    } catch {
      if (hasStoredToken) {
        clearAuthState()
      } else {
        writeState(getGuestState())
      }
    } finally {
      authBootstrapPromise = null
    }
  })()

  return authBootstrapPromise
}

export function installAuthFetchInterceptor() {
  if (fetchInterceptorInstalled || typeof window === 'undefined') return
  fetchInterceptorInstalled = true

  const originalFetch = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input, init)
    const isApiRequest = isApiRequestUrl(input, request)

    if (isApiRequest && authState.accessToken && !request.headers.has('Authorization')) {
      request.headers.set('Authorization', `Bearer ${authState.accessToken}`)
    }

    const hadToken = Boolean(authState.accessToken)
    const response = await originalFetch(request)
    if (isApiRequest && response.status === 401 && hadToken && !isAuthRoute(new URL(request.url, window.location.origin).pathname)) {
      clearAuthState('登录已过期，请重新登录')
      redirectToLogin()
    }
    return response
  }
}
