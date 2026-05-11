import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getNavState } from '../../api/navApi'
import {
  getPcdSceneMetadata,
  getPcdScenePreview,
  listPcdScenes,
  listWaypoints,
  selectPcdScene,
} from '../../api/pcdMapApi'
import type { GlobalPath, LocalizationStatus, NavigationStatus, RobotPose } from '../../types/navState'
import type { NavWaypoint, PcdSceneItem, PcdSceneMetadata, PcdScenePreview, PcdSceneLayerRole } from '../../types/pcdMap'

const SELECTED_SCENE_STORAGE_KEY = 'botdog-nav-selected-scene'

type PointCloudLayer = {
  role: PcdSceneLayerRole
  points: [number, number, number][]
}

type InitialStatePayload = {
  robotPose?: RobotPose | null
  globalPath?: GlobalPath | null
  localizationStatus?: LocalizationStatus | null
  navigationStatus?: NavigationStatus | null
}

export type UseNavScenesOptions = {
  previewPointLimit: number
  setInitialState: (state: InitialStatePayload) => void
  onWaypointsLoaded: (waypoints: NavWaypoint[]) => void
  onLog: (message: string, level?: 'info' | 'error') => void
}

export function useNavScenes({
  previewPointLimit,
  setInitialState,
  onWaypointsLoaded,
  onLog,
}: UseNavScenesOptions) {
  const [scenes, setScenes] = useState<PcdSceneItem[]>([])
  const [root, setRoot] = useState('')
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null
    return window.localStorage.getItem(SELECTED_SCENE_STORAGE_KEY)
  })
  const [metadata, setMetadata] = useState<PcdSceneMetadata | null>(null)
  const [preview, setPreview] = useState<PcdScenePreview | null>(null)
  const [loading, setLoading] = useState(false)
  const selectRequestRef = useRef(0)
  const noAvailableSceneLoggedRef = useRef(false)

  const selectedScene = useMemo(
    () => scenes.find((scene) => scene.id === selectedSceneId) ?? null,
    [scenes, selectedSceneId],
  )

  const selectedSceneReady = selectedScene?.ready ?? false
  const selectedSceneNavigable = selectedScene?.navigable ?? false
  const selectedSceneMessage = selectedScene?.message ?? metadata?.message ?? null

  const previewLayers = useMemo<PointCloudLayer[]>(
    () => [
      { role: 'ground', points: preview?.layers.ground?.points ?? [] },
      { role: 'wall', points: preview?.layers.wall?.points ?? [] },
    ],
    [preview],
  )

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (selectedSceneId) {
      window.localStorage.setItem(SELECTED_SCENE_STORAGE_KEY, selectedSceneId)
    } else {
      window.localStorage.removeItem(SELECTED_SCENE_STORAGE_KEY)
    }
  }, [selectedSceneId])

  const refreshScenes = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listPcdScenes()
      setScenes(data.items)
      setRoot(data.root)
      onLog(`已刷新场景目录，共 ${data.items.length} 个场景文件夹`)
    } catch (error) {
      onLog(error instanceof Error ? error.message : '获取场景列表失败', 'error')
    } finally {
      setLoading(false)
    }
  }, [onLog])

  const selectScene = useCallback(async (sceneId: string) => {
    const requestId = ++selectRequestRef.current
    setLoading(true)
    noAvailableSceneLoggedRef.current = false

    try {
      const currentScene = await selectPcdScene(sceneId)
      if (requestId !== selectRequestRef.current) return

      setSelectedSceneId(currentScene.scene_id)
      setMetadata(null)
      setPreview(null)
      onWaypointsLoaded([])
      onLog(`当前选择导航场景：${currentScene.scene_id}`)
      onLog(`当前场景 map.pcd：${currentScene.map_pcd}`)
      onLog(`当前场景 ground.pcd：${currentScene.ground_pcd}`)

      const nextMetadata = await getPcdSceneMetadata(sceneId)
      if (requestId !== selectRequestRef.current) return
      setMetadata(nextMetadata)
      onLog(`已读取场景 metadata: ${sceneId}`)

      const [nextPreview, nextWaypoints] = await Promise.all([
        getPcdScenePreview(sceneId, previewPointLimit),
        listWaypoints(sceneId).catch(() => ({ items: [] as NavWaypoint[] })),
      ])
      if (requestId !== selectRequestRef.current) return
      setPreview(nextPreview)
      onWaypointsLoaded(nextWaypoints.items)
      const groundPoints = nextPreview.layers.ground?.points.length || 0
      const wallPoints = nextPreview.layers.wall?.points.length || 0
      onLog(`已加载场景预览点云：ground ${groundPoints.toLocaleString()} 点，wall ${wallPoints.toLocaleString()} 点`)

      try {
        const navState = await getNavState()
        if (requestId !== selectRequestRef.current) return
        setInitialState({
          robotPose: navState.robot_pose,
          globalPath: navState.global_path,
          localizationStatus: navState.localization_status,
          navigationStatus: navState.navigation_status,
        })
        onLog('已刷新导航实时状态')
      } catch (error) {
        if (requestId === selectRequestRef.current) {
          onLog(error instanceof Error ? error.message : '刷新导航状态失败', 'error')
        }
      }
    } catch (error) {
      if (requestId !== selectRequestRef.current) return
      onLog(error instanceof Error ? error.message : `加载场景失败: ${sceneId}`, 'error')
    } finally {
      if (requestId === selectRequestRef.current) {
        setLoading(false)
      }
    }
  }, [onWaypointsLoaded, onLog, previewPointLimit, setInitialState])

  useEffect(() => {
    void refreshScenes()
  }, [refreshScenes])

  useEffect(() => {
    if (scenes.length === 0) return
    if (loading) return

    if (selectedSceneId && scenes.some((item) => item.id === selectedSceneId)) {
      if (metadata?.scene_id !== selectedSceneId) {
        void selectScene(selectedSceneId)
      }
      noAvailableSceneLoggedRef.current = false
      return
    }

    const storedSceneId = typeof window === 'undefined'
      ? null
      : window.localStorage.getItem(SELECTED_SCENE_STORAGE_KEY)

    if (storedSceneId && scenes.some((item) => item.id === storedSceneId)) {
      void selectScene(storedSceneId)
      noAvailableSceneLoggedRef.current = false
      return
    }

    const readyScene = scenes.find((item) => item.ready)
    if (readyScene) {
      void selectScene(readyScene.id)
      noAvailableSceneLoggedRef.current = false
      return
    }

    setSelectedSceneId(null)
    setMetadata(null)
    setPreview(null)
    onWaypointsLoaded([])
    if (!noAvailableSceneLoggedRef.current) {
      onLog('当前没有可用于导航的场景')
      noAvailableSceneLoggedRef.current = true
    }
  }, [loading, metadata?.scene_id, onLog, onWaypointsLoaded, scenes, selectScene, selectedSceneId])

  return {
    scenes,
    root,
    selectedSceneId,
    setSelectedSceneId,
    selectedScene,
    selectedSceneReady,
    selectedSceneNavigable,
    selectedSceneMessage,
    metadata,
    preview,
    loading,
    refreshScenes,
    selectScene,
    previewLayers,
  }
}
