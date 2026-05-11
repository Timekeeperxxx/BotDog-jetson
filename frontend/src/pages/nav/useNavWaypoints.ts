import { useCallback, useMemo } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { createWaypoint, deleteWaypoint, goToWaypoint, listWaypoints } from '../../api/pcdMapApi'
import type { NavWaypoint } from '../../types/pcdMap'

type WaypointStateSetter<T> = Dispatch<SetStateAction<T>>

export type UseNavWaypointsOptions = {
  selectedSceneId: string | null
  selectedSceneNavigable: boolean
  canOperate: boolean
  waypoints: NavWaypoint[]
  setWaypoints: WaypointStateSetter<NavWaypoint[]>
  setAddMode: WaypointStateSetter<boolean>
  setNavigatingWaypointId: WaypointStateSetter<string | null>
  setGoToConfirm: WaypointStateSetter<NavWaypoint | null>
  onLog: (message: string, level?: 'info' | 'error') => void
  onExitToolMode?: () => void
}

export function useNavWaypoints({
  selectedSceneId,
  selectedSceneNavigable,
  canOperate,
  waypoints,
  setWaypoints,
  setAddMode,
  setNavigatingWaypointId,
  setGoToConfirm,
  onLog,
  onExitToolMode,
}: UseNavWaypointsOptions) {
  const handleAddWaypoint = useCallback(async (pos: { x: number; y: number; z: number; yaw: number }) => {
    if (!selectedSceneId) return
    if (!selectedSceneNavigable) {
      onLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
      return
    }

    const defaultName = `巡检点${waypoints.length + 1}`
    const name = window.prompt('导航点名称', defaultName)?.trim()
    if (!name) return

    try {
      await createWaypoint(selectedSceneId, {
        name,
        x: pos.x,
        y: pos.y,
        z: pos.z,
        yaw: pos.yaw,
        frame_id: 'map',
      })
      const nextWaypoints = await listWaypoints(selectedSceneId)
      setWaypoints(nextWaypoints.items)
      setAddMode(false)
      onLog(
        `已保存导航点 ${name}: x=${pos.x.toFixed(3)}, y=${pos.y.toFixed(3)}, z=${pos.z.toFixed(3)}, yaw=${pos.yaw.toFixed(3)}`,
      )
    } catch (error) {
      onLog(error instanceof Error ? error.message : '保存导航点失败', 'error')
    }
  }, [onLog, selectedSceneId, selectedSceneNavigable, setAddMode, setWaypoints, waypoints.length])

  const handleDeleteWaypoint = useCallback(async (waypointId: string) => {
    if (!selectedSceneId) return

    try {
      await deleteWaypoint(selectedSceneId, waypointId)
      const nextWaypoints = await listWaypoints(selectedSceneId)
      setWaypoints(nextWaypoints.items)
      onLog(`已删除导航点 ${waypointId}`)
    } catch (error) {
      onLog(error instanceof Error ? error.message : '删除导航点失败', 'error')
    }
  }, [onLog, selectedSceneId, setWaypoints])

  const requestGoToWaypoint = useCallback((waypointId: string) => {
    if (!canOperate) return
    const waypoint = waypoints.find((item) => item.id === waypointId)
    if (!waypoint) return
    setGoToConfirm(waypoint)
  }, [canOperate, setGoToConfirm, waypoints])

  const handleGoToWaypoint = useCallback(async (waypointId: string) => {
    if (!selectedSceneId) return
    if (!canOperate || !selectedSceneNavigable) {
      onLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
      return
    }

    setNavigatingWaypointId(waypointId)
    try {
      const result = await goToWaypoint(selectedSceneId, waypointId)
      const waypoint = waypoints.find((item) => item.id === waypointId)
      onLog(`已发布导航目标 ${waypoint?.name || waypointId} 到 ${result.topic}`)
    } catch (error) {
      onLog(error instanceof Error ? error.message : '发布导航目标失败', 'error')
    } finally {
      setNavigatingWaypointId(null)
    }
  }, [canOperate, onLog, selectedSceneId, selectedSceneNavigable, setNavigatingWaypointId, waypoints])

  const handleToggleWaypointMode = useCallback(() => {
    setAddMode((value) => {
      const nextValue = !value
      if (nextValue) {
        onExitToolMode?.()
      }
      onLog(nextValue ? '已切换到添加导航点模式' : '已退出标点')
      return nextValue
    })
  }, [onExitToolMode, onLog, setAddMode])

  const selectedSceneWaypoints = useMemo(
    () => waypoints.map((waypoint) => ({ id: waypoint.id, name: waypoint.name })),
    [waypoints],
  )

  return {
    handleAddWaypoint,
    handleDeleteWaypoint,
    requestGoToWaypoint,
    handleGoToWaypoint,
    handleToggleWaypointMode,
    selectedSceneWaypoints,
  }
}
