import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getNavState } from '../../api/navApi'
import {
  getPcdSceneMetadata,
  getPcdScenePreview,
  getPcdSceneTile,
  getPcdSceneTileManifest,
  listPcdScenes,
  listWaypoints,
  selectPcdScene,
} from '../../api/pcdMapApi'
import type { GlobalPath, LocalizationStatus, NavigationStatus, RobotPose } from '../../types/navState'
import type { NavWaypoint, PcdSceneItem, PcdSceneMetadata, PcdScenePreview, PcdSceneLayerRole, PcdSceneRootTile, PcdSceneTileManifest, PointCloudPoints } from '../../types/pcdMap'
import { getPointCount } from '../../utils/pointCloudPoints'

const SELECTED_SCENE_STORAGE_KEY = 'botdog-nav-selected-scene'

type PointCloudLayer = {
  role: PcdSceneLayerRole
  points: PointCloudPoints
  intensity?: Uint8Array
  coordinateSpace?: 'map' | 'three'
}

export function decodeTopDownOverviewTile(tile: PcdSceneRootTile, buffer: ArrayBuffer): PointCloudLayer {
  const expectedBytes = tile.point_count * (tile.has_intensity ? 13 : 12)
  if (tile.byte_length !== expectedBytes || buffer.byteLength !== expectedBytes) {
    throw new Error(`2D 概览瓦片长度不匹配: ${tile.file}`)
  }
  return {
    role: tile.role,
    points: new Float32Array(buffer, 0, tile.point_count * 3),
    // 分块文件直接存储 Three.js (x, z, -y)，2D 绘制时再映射回地图 XY，避免复制点数组。
    coordinateSpace: 'three',
  }
}

type InitialStatePayload = {
  robotPose?: RobotPose | null
  globalPath?: GlobalPath | null
  executionPath?: GlobalPath | null
  localizationStatus?: LocalizationStatus | null
  navigationStatus?: NavigationStatus | null
}

export type UseNavScenesOptions = {
  setInitialState: (state: InitialStatePayload) => void
  onWaypointsLoaded: (waypoints: NavWaypoint[]) => void
  onLog: (message: string, level?: 'info' | 'error') => void
  onSceneChanging?: () => void
}

export function useNavScenes({
  setInitialState,
  onWaypointsLoaded,
  onLog,
  onSceneChanging,
}: UseNavScenesOptions) {
  const [scenes, setScenes] = useState<PcdSceneItem[]>([])
  const [root, setRoot] = useState('')
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null
    return window.localStorage.getItem(SELECTED_SCENE_STORAGE_KEY)
  })
  const [metadata, setMetadata] = useState<PcdSceneMetadata | null>(null)
  const [preview, setPreview] = useState<PcdScenePreview | null>(null)
  const [tileManifest, setTileManifest] = useState<PcdSceneTileManifest | null>(null)
  const [tileOverviewLayers, setTileOverviewLayers] = useState<PointCloudLayer[]>([])
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
      {
        role: 'ground',
        points: tileManifest ? [] : (preview?.layers.ground?.points ?? []),
        intensity: preview?.layers.ground?.intensity,
      },
      {
        role: 'wall',
        points: tileManifest ? [] : (preview?.layers.wall?.points ?? []),
        intensity: preview?.layers.wall?.intensity,
      },
      {
        role: 'footprint_fill',
        points: tileManifest ? [] : (preview?.layers.footprint_fill?.points ?? []),
        intensity: preview?.layers.footprint_fill?.intensity,
      },
    ],
    [preview, tileManifest],
  )

  useEffect(() => {
    if (!tileManifest) {
      setTileOverviewLayers([])
      return
    }

    const controller = new AbortController()
    setTileOverviewLayers([])
    void Promise.all(
      tileManifest.root_tiles.map(async (tile) => {
        const buffer = await getPcdSceneTile(
          tileManifest.scene_id,
          tile.file,
          tileManifest.cache_key,
          controller.signal,
        )
        return decodeTopDownOverviewTile(tile, buffer)
      }),
    ).then((layers) => {
      if (controller.signal.aborted) return
      setTileOverviewLayers(layers)
      const pointCount = layers.reduce((sum, layer) => sum + getPointCount(layer.points), 0)
      onLog(`2D 俯视概览已加载：${pointCount.toLocaleString()} 点`)
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return
      onLog(error instanceof Error ? error.message : '2D 俯视概览加载失败', 'error')
    })

    return () => controller.abort()
  }, [onLog, tileManifest])

  const topDownLayers = useMemo(
    () => tileManifest ? tileOverviewLayers : previewLayers,
    [previewLayers, tileManifest, tileOverviewLayers],
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

  const selectScene = useCallback(async (sceneId: string): Promise<boolean> => {
    const requestId = ++selectRequestRef.current
    let selectionApplied = false
    setLoading(true)
    noAvailableSceneLoggedRef.current = false

    try {
      const currentScene = await selectPcdScene(sceneId)
      if (requestId !== selectRequestRef.current) return false

      selectionApplied = true
      setSelectedSceneId(currentScene.scene_id)
      setMetadata(null)
      setPreview(null)
      setTileManifest(null)
      onWaypointsLoaded([])
      onSceneChanging?.()
      onLog(`当前选择导航场景：${currentScene.scene_id}`)
      onLog(`当前场景 map.pcd：${currentScene.map_pcd}`)
      onLog(`当前场景 ground.pcd：${currentScene.ground_pcd}`)

      const nextMetadata = await getPcdSceneMetadata(sceneId)
      if (requestId !== selectRequestRef.current) return false
      setMetadata(nextMetadata)
      onLog(`已读取场景 metadata: ${sceneId}`)

      const [pointCloudData, nextWaypoints] = await Promise.all([
        getPcdSceneTileManifest(sceneId)
          .then((manifest) => ({ manifest, preview: null as PcdScenePreview | null }))
          .catch(async (error: unknown) => {
            // 兼容前端先于后端发布的窗口；新后端构建失败时不再退回超大单体文件。
            if (!(error instanceof Error) || !['HTTP 404', 'Not Found'].includes(error.message)) {
              throw error
            }
            return { manifest: null, preview: await getPcdScenePreview(sceneId) }
          }),
        listWaypoints(sceneId).catch(() => ({ items: [] as NavWaypoint[] })),
      ])
      if (requestId !== selectRequestRef.current) return false
      setTileManifest(pointCloudData.manifest)
      setPreview(pointCloudData.preview)
      onWaypointsLoaded(nextWaypoints.items)
      if (pointCloudData.manifest) {
        const rootPoints = pointCloudData.manifest.root_tiles.reduce((sum, tile) => sum + tile.point_count, 0)
        onLog(
          `已加载分层点云索引：首屏 ${rootPoints.toLocaleString()} 点，${pointCloudData.manifest.nodes.length.toLocaleString()} 个空间瓦片`,
        )
      } else if (pointCloudData.preview) {
        const nextPreview = pointCloudData.preview
        const groundPoints = nextPreview.layers.ground ? getPointCount(nextPreview.layers.ground.points) : 0
        const wallPoints = nextPreview.layers.wall ? getPointCount(nextPreview.layers.wall.points) : 0
        const footprintFillPoints = nextPreview.layers.footprint_fill
          ? getPointCount(nextPreview.layers.footprint_fill.points)
          : 0
        onLog(
          `已加载兼容点云预览：ground ${groundPoints.toLocaleString()} 点，wall ${wallPoints.toLocaleString()} 点，footprint_fill ${footprintFillPoints.toLocaleString()} 点`,
        )
      }

      try {
        const navState = await getNavState()
        if (requestId !== selectRequestRef.current) return false
        setInitialState({
          robotPose: navState.robot_pose,
          globalPath: navState.global_path,
          executionPath: navState.execution_path,
          localizationStatus: navState.localization_status,
          navigationStatus: navState.navigation_status,
        })
        onLog('已刷新导航实时状态')
      } catch (error) {
        if (requestId === selectRequestRef.current) {
          onLog(error instanceof Error ? error.message : '刷新导航状态失败', 'error')
        }
      }
      return true
    } catch (error) {
      if (requestId !== selectRequestRef.current) return false
      onLog(error instanceof Error ? error.message : `加载场景失败: ${sceneId}`, 'error')
      return selectionApplied
    } finally {
      if (requestId === selectRequestRef.current) {
        setLoading(false)
      }
    }
  }, [onSceneChanging, onWaypointsLoaded, onLog, setInitialState])

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
    setTileManifest(null)
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
    tileManifest,
    loading,
    refreshScenes,
    selectScene,
    previewLayers,
    topDownLayers,
  }
}
