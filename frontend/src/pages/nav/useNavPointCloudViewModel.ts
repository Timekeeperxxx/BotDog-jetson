import { useMemo } from 'react'
import type { GlobalPath, RobotPose } from '../../types/navState'
import type { NavWaypoint, PcdBounds, PcdSceneMetadata, PcdScenePreview, PcdSceneTileManifest } from '../../types/pcdMap'
import type { PointCloudLayer } from './NavPageShell'
import type { PcdLayerVisibility } from './NavToolStrip'
import type { MappingSessionInfo } from './navPageUtils'
import { trimGlobalPathByRobotPose } from './navPageUtils'

type UseNavPointCloudViewModelOptions = {
  executionPath: GlobalPath | null
  globalPath: GlobalPath | null
  liveMappingCloudPoints: [number, number, number][]
  mappingActive: boolean
  mappingCloudPoints: [number, number, number][]
  mappingSessionInfo: MappingSessionInfo | null
  metadata: PcdSceneMetadata | null
  pcdLayerVisibility: PcdLayerVisibility
  preview: PcdScenePreview | null
  previewLayers: PointCloudLayer[]
  topDownLayers: PointCloudLayer[]
  tileManifest: PcdSceneTileManifest | null
  robotPose: RobotPose | null
  selectedSceneId: string | null
  waypoints: NavWaypoint[]
}

export function useNavPointCloudViewModel({
  executionPath,
  globalPath,
  liveMappingCloudPoints,
  mappingActive,
  mappingCloudPoints,
  mappingSessionInfo,
  metadata,
  pcdLayerVisibility,
  preview,
  previewLayers,
  topDownLayers,
  tileManifest,
  robotPose,
  selectedSceneId,
  waypoints,
}: UseNavPointCloudViewModelOptions) {
  const allLayers = useMemo(() => {
    if (!mappingActive) {
      return previewLayers.filter((layer) => {
        if (layer.role === 'wall') return pcdLayerVisibility.map
        if (layer.role === 'ground') return pcdLayerVisibility.ground
        if (layer.role === 'footprint_fill') return pcdLayerVisibility.footprint
        return true
      })
    }
    if (mappingCloudPoints.length === 0 && liveMappingCloudPoints.length === 0) return []

    const layers: PointCloudLayer[] = []
    if (mappingCloudPoints.length > 0) {
      layers.push({ role: 'mapping', points: mappingCloudPoints })
    }
    if (liveMappingCloudPoints.length > 0) {
      layers.push({ role: 'live', points: liveMappingCloudPoints })
    }
    return layers
  }, [
    previewLayers,
    mappingActive,
    mappingCloudPoints,
    liveMappingCloudPoints,
    pcdLayerVisibility,
  ])

  const pointCloudViewKey = mappingActive
    ? `mapping:${mappingSessionInfo?.sceneName || mappingSessionInfo?.mapDir || 'active'}`
    : `scene:${selectedSceneId || 'none'}`

  const rightRailLayers = useMemo(() => {
    if (mappingActive) return allLayers
    return topDownLayers.filter((layer) => {
      if (layer.role === 'wall') return pcdLayerVisibility.map
      if (layer.role === 'ground') return pcdLayerVisibility.ground
      if (layer.role === 'footprint_fill') return pcdLayerVisibility.footprint
      return true
    })
  }, [allLayers, mappingActive, pcdLayerVisibility, topDownLayers])

  const liveMappingBounds = useMemo<PcdBounds | null>(() => {
    if (!mappingActive || (mappingCloudPoints.length === 0 && liveMappingCloudPoints.length === 0)) return null

    let minX = Number.POSITIVE_INFINITY
    let maxX = Number.NEGATIVE_INFINITY
    let minY = Number.POSITIVE_INFINITY
    let maxY = Number.NEGATIVE_INFINITY
    let minZ = Number.POSITIVE_INFINITY
    let maxZ = Number.NEGATIVE_INFINITY

    const updateBounds = ([x, y, z]: [number, number, number]) => {
      minX = Math.min(minX, x)
      maxX = Math.max(maxX, x)
      minY = Math.min(minY, y)
      maxY = Math.max(maxY, y)
      minZ = Math.min(minZ, z)
      maxZ = Math.max(maxZ, z)
    }

    mappingCloudPoints.forEach(updateBounds)
    liveMappingCloudPoints.forEach(updateBounds)

    return {
      min_x: minX,
      max_x: maxX,
      min_y: minY,
      max_y: maxY,
      min_z: minZ,
      max_z: maxZ,
    }
  }, [mappingActive, mappingCloudPoints, liveMappingCloudPoints])

  const groundCenterHeight = useMemo(() => {
    const bounds = tileManifest?.layer_bounds.ground ?? preview?.layers.ground?.bounds ?? metadata?.files.ground?.bounds ?? null
    return bounds ? (bounds.min_z + bounds.max_z) / 2 : null
  }, [metadata?.files.ground?.bounds, preview?.layers.ground?.bounds, tileManifest?.layer_bounds.ground])

  const displayedGlobalPath = useMemo(
    () => trimGlobalPathByRobotPose(globalPath, robotPose),
    [globalPath, robotPose],
  )

  const selectedSceneWaypoints = useMemo(
    () => waypoints.map((waypoint) => ({ id: waypoint.id, name: waypoint.name })),
    [waypoints],
  )

  const rightRailBounds = mappingActive
    ? liveMappingBounds
    : (tileManifest?.bounds || preview?.bounds || metadata?.bounds || null)

  return {
    allLayers,
    displayedExecutionPath: executionPath,
    displayedGlobalPath,
    groundCenterHeight,
    pointCloudViewKey,
    rightRailBounds,
    rightRailLayers,
    selectedSceneWaypoints,
  }
}
