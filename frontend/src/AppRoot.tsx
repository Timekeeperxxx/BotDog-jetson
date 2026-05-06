import { useEffect } from 'react'
import IndustrialConsoleComplete from './IndustrialConsoleComplete'
import { AdminApp } from './admin/AdminApp'
import { LoginPage } from './pages/LoginPage'
import { bootstrapAuthState, hasAuthSession, installAuthFetchInterceptor, useAuthState } from './stores/authStore'

installAuthFetchInterceptor()

function getNormalizedPathname() {
  const pathname = window.location.pathname || '/'
  if (pathname === '/index.html') return '/'
  return pathname
}

export function AppRoot() {
  const pathname = getNormalizedPathname()
  const auth = useAuthState()

  useEffect(() => {
    void bootstrapAuthState()
  }, [])

  if (!auth.ready && auth.validating) {
    return (
      <div className="min-h-screen bg-[#050506] text-white flex items-center justify-center px-6">
        <div className="border border-white/10 bg-black/70 px-6 py-5 text-sm text-zinc-300">
          正在校验登录状态...
        </div>
      </div>
    )
  }

  if (pathname === '/login') {
    if (hasAuthSession()) {
      window.location.assign('/')
      return null
    }
    return <LoginPage />
  }

  if (pathname === '/admin' || pathname.startsWith('/admin/')) {
    if (!hasAuthSession()) {
      return <LoginPage />
    }
    return <AdminApp />
  }

  return <IndustrialConsoleComplete />
}
