import { useCallback, useEffect, useState } from 'react'
import { deleteWaypoint, getPcdMetadata, listPcdMaps, listWaypoints } from '../../api/pcdMapApi'
import type { NavWaypoint, PcdMapItem, PcdMetadata } from '../../types/pcdMap'
import type { TaskDefinition } from '../../types/taskWorkflow'

const TASK_STORAGE_KEY = 'botdog-nav-workflows'

export function readStoredTasks(): TaskDefinition[] {
  try {
    const raw = window.localStorage.getItem(TASK_STORAGE_KEY)
    if (!raw) return []
    return JSON.parse(raw) as TaskDefinition[]
  } catch {
    return []
  }
}

export function useAdminNavigationData() {
  const [maps, setMaps] = useState<PcdMapItem[]>([])
  const [selectedMapId, setSelectedMapId] = useState<string | null>(null)
  const [metadata, setMetadata] = useState<PcdMetadata | null>(null)
  const [waypoints, setWaypoints] = useState<NavWaypoint[]>([])
  const [tasks, setTasks] = useState<TaskDefinition[]>([])
  const [navSearch, setNavSearch] = useState('')
  const [waypointToDelete, setWaypointToDelete] = useState<NavWaypoint | null>(null)

  const refreshMapDetails = useCallback(async (mapId: string) => {
    const [nextMetadata, nextWaypoints] = await Promise.all([
      getPcdMetadata(mapId).catch(() => null),
      listWaypoints(mapId).catch(() => ({ items: [] as NavWaypoint[] })),
    ])
    setMetadata(nextMetadata)
    setWaypoints(nextWaypoints.items || [])
  }, [])

  const refreshNavigationData = useCallback(async () => {
    const nextMaps = await listPcdMaps().catch(() => ({ root: '', items: [] as PcdMapItem[] }))
    setMaps(nextMaps.items || [])
    setTasks(readStoredTasks())
    setSelectedMapId((current) => current || nextMaps.items[0]?.id || null)
  }, [])

  const deleteSelectedWaypoint = useCallback(async () => {
    if (!selectedMapId || !waypointToDelete) return
    await deleteWaypoint(selectedMapId, waypointToDelete.id)
    await refreshMapDetails(selectedMapId)
  }, [refreshMapDetails, selectedMapId, waypointToDelete])

  useEffect(() => {
    void refreshNavigationData()
  }, [refreshNavigationData])

  useEffect(() => {
    if (!selectedMapId) return
    void refreshMapDetails(selectedMapId)
  }, [refreshMapDetails, selectedMapId])

  return {
    maps,
    selectedMapId,
    setSelectedMapId,
    metadata,
    waypoints,
    tasks,
    navSearch,
    setNavSearch,
    waypointToDelete,
    setWaypointToDelete,
    refreshNavigationData,
    refreshMapDetails,
    deleteSelectedWaypoint,
  }
}
