import type { AdminDashboardData } from '../adminTypes'
import { AdminDevicePage } from './AdminDevicePage'

export function AdminDashboardPage({
  data,
  onRefresh,
  canManageSystem,
}: {
  data: AdminDashboardData
  onRefresh: () => void
  canManageSystem: boolean
}) {
  return (
    <AdminDevicePage
      data={{
        systemInfo: data.systemInfo,
        networkInterfaces: data.networkInterfaces,
        health: data.health,
        navState: data.navState,
        aiStatus: data.aiStatus,
        autoTrackStatus: data.autoTrackStatus,
        hostResources: data.hostResources,
      }}
      onRefresh={onRefresh}
      canManageSystem={canManageSystem}
    />
  )
}
