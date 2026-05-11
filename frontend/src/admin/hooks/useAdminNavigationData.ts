import { useCallback, useEffect, useState } from 'react'
import { deleteWaypoint, getPcdSceneMetadata, listNavTasks, listPcdScenes, listWaypoints } from '../../api/pcdMapApi'
import type { NavWaypoint, PcdSceneItem, PcdSceneMetadata } from '../../types/pcdMap'
import type { TaskDefinition } from '../../types/taskWorkflow'

export function useAdminNavigationData() {
  const [scenes, setScenes] = useState<PcdSceneItem[]>([])
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null)
  const [metadata, setMetadata] = useState<PcdSceneMetadata | null>(null)
  const [waypoints, setWaypoints] = useState<NavWaypoint[]>([])
  const [tasks, setTasks] = useState<TaskDefinition[]>([])
  const [navSearch, setNavSearch] = useState('')
  const [waypointToDelete, setWaypointToDelete] = useState<NavWaypoint | null>(null)

  const refreshSceneDetails = useCallback(async (sceneId: string) => {
    const [nextMetadata, nextWaypoints] = await Promise.all([
      getPcdSceneMetadata(sceneId).catch(() => null),
      listWaypoints(sceneId).catch(() => ({ items: [] as NavWaypoint[] })),
    ])
    setMetadata(nextMetadata)
    setWaypoints(nextWaypoints.items || [])
  }, [])

  const refreshNavigationData = useCallback(async () => {
    const [nextScenes, nextTasks] = await Promise.all([
      listPcdScenes().catch(() => ({ root: '', items: [] as PcdSceneItem[] })),
      listNavTasks().catch(() => ({ items: [] as TaskDefinition[] })),
    ])
    setScenes(nextScenes.items || [])
    setTasks(nextTasks.items || [])
    setSelectedSceneId((current) => current || nextScenes.items[0]?.id || null)
  }, [])

  const deleteSelectedWaypoint = useCallback(async () => {
    if (!selectedSceneId || !waypointToDelete) return
    await deleteWaypoint(selectedSceneId, waypointToDelete.id)
    await refreshSceneDetails(selectedSceneId)
  }, [refreshSceneDetails, selectedSceneId, waypointToDelete])

  useEffect(() => {
    void refreshNavigationData()
  }, [refreshNavigationData])

  useEffect(() => {
    if (!selectedSceneId) return
    void refreshSceneDetails(selectedSceneId)
  }, [refreshSceneDetails, selectedSceneId])

  return {
    scenes,
    maps: scenes,
    selectedSceneId,
    selectedMapId: selectedSceneId,
    setSelectedSceneId,
    setSelectedMapId: setSelectedSceneId,
    metadata,
    waypoints,
    tasks,
    navSearch,
    setNavSearch,
    waypointToDelete,
    setWaypointToDelete,
    refreshNavigationData,
    refreshSceneDetails,
    refreshMapDetails: refreshSceneDetails,
    deleteSelectedWaypoint,
  }
}
