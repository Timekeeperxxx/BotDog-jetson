import { useCallback, useEffect, useState } from 'react'
import { getNavState } from '../../api/navApi'
import { getAdminLogs, getSystemHealth, getSystemInfo, getSystemResources } from '../adminApi'
import type { AdminLogEntry, HealthResponse, HostResources, SystemInfoGroup } from '../adminTypes'
import type { NavStateResponse } from '../../types/navState'

export function useAdminCoreData() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [systemInfo, setSystemInfo] = useState<SystemInfoGroup[]>([])
  const [hostResources, setHostResources] = useState<HostResources | null>(null)
  const [logs, setLogs] = useState<AdminLogEntry[]>([])
  const [navState, setNavState] = useState<NavStateResponse | null>(null)
  const [adminLoading, setAdminLoading] = useState(false)
  const [adminError, setAdminError] = useState<string | null>(null)

  const refreshAdminCore = useCallback(async () => {
    setAdminLoading(true)
    setAdminError(null)
    try {
      const [nextHealth, nextInfo, nextResources, nextLogs, nextNavState] = await Promise.all([
        getSystemHealth(),
        getSystemInfo(),
        getSystemResources().catch(() => null),
        getAdminLogs(),
        getNavState().catch(() => null),
      ])
      setHealth(nextHealth)
      setSystemInfo(nextInfo.groups || [])
      setHostResources(nextResources)
      setLogs(nextLogs.items || [])
      setNavState(nextNavState)
    } catch (error) {
      setAdminError(error instanceof Error ? error.message : '后台数据加载失败')
    } finally {
      setAdminLoading(false)
    }
  }, [])

  useEffect(() => {
    void refreshAdminCore()
  }, [refreshAdminCore])

  return {
    health,
    systemInfo,
    hostResources,
    logs,
    navState,
    adminLoading,
    adminError,
    refreshAdminCore,
  }
}
