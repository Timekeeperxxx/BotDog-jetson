import IndustrialConsoleComplete from './IndustrialConsoleComplete'
import { AdminApp } from './admin/AdminApp'

function getNormalizedPathname() {
  const pathname = window.location.pathname || '/'
  if (pathname === '/index.html') return '/'
  return pathname
}

export function AppRoot() {
  const pathname = getNormalizedPathname()

  if (pathname === '/admin' || pathname.startsWith('/admin/')) {
    return <AdminApp />
  }

  return <IndustrialConsoleComplete />
}
