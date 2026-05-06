import type { ReactNode } from 'react'
import { hasAuthSession, hasRole, useAuthState } from '../stores/authStore'

type Props = {
  requiredRole: 'viewer' | 'operator' | 'admin'
  fallback?: ReactNode
  children: ReactNode
}

export function PermissionGuard({ requiredRole, fallback = null, children }: Props) {
  useAuthState()
  if (!hasAuthSession() || !hasRole(requiredRole)) {
    return <>{fallback}</>
  }
  return <>{children}</>
}
