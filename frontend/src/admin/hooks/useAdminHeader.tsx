import { useMemo, type ReactNode } from 'react'
import { MapPinned, Network, RefreshCw } from 'lucide-react'
import { ToolbarButton } from '../AdminUi'
import { adminNavItems } from '../adminMenu'
import type { AdminHeaderStatusItem } from '../components/AdminHeader'
import type { AdminRole } from '../components/AdminSidebar'
import type { AdminSection } from '../adminTypes'
import type { EventHookState } from '../../hooks/useEventWebSocket'

type UseAdminHeaderOptions = {
  activeSection: AdminSection
  role: AdminRole
  eventState: EventHookState
  navConnected: boolean
  healthStatus: string | null | undefined
  adminLoading: boolean
  refreshAdminCore: () => Promise<void> | void
}

export function useAdminHeader({
  activeSection,
  role,
  eventState,
  navConnected,
  healthStatus,
  adminLoading,
  refreshAdminCore,
}: UseAdminHeaderOptions) {
  const sectionMeta = useMemo(
    () => adminNavItems.find((item) => item.key === activeSection) ?? adminNavItems[0],
    [activeSection],
  )

  const headerStatusItems = useMemo<AdminHeaderStatusItem[]>(() => [
    { icon: <Network size={14} />, label: '事件流', value: eventState.status.status },
    { icon: <MapPinned size={14} />, label: '导航', value: navConnected ? 'ws已连接' : 'ws离线' },
    { icon: <RefreshCw size={14} />, label: '健康状态', value: healthStatus || '等待中' },
  ], [eventState.status.status, healthStatus, navConnected])

  const headerActions: ReactNode = useMemo(() => (
    <>
      <ToolbarButton
        onClick={() => window.location.assign('/operator')}
        disabled={role === 'viewer'}
        title={role === 'viewer' ? '需要 operator 权限' : undefined}
      >
        进入操作台
      </ToolbarButton>
      <ToolbarButton onClick={() => void refreshAdminCore()}>{adminLoading ? '刷新中' : '刷新总览'}</ToolbarButton>
    </>
  ), [adminLoading, refreshAdminCore, role])

  return {
    sectionMeta,
    headerStatusItems,
    headerActions,
  }
}
