import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type {
  NavWaypoint,
  NavFence,
  PcdSceneLayerRole,
  PcdSceneTileManifest,
  PointCloudQualityMode,
  PointCloudPoints,
  WallColorMode,
} from '../../types/pcdMap'
import type { GlobalPath, RobotPose } from '../../types/navState'
import { mapToThree, threeToMap } from '../../utils/pointCloudTransform'
import { getPointCount } from '../../utils/pointCloudPoints'
import { advanceFenceDraft } from '../../utils/fenceDraft'
import { detectWebGLSupport } from './webglSupport'
import {
  PointCloudTileManager,
  type PointCloudTileStats,
} from './PointCloudTileManager'
import {
  GLOBAL_PATH_NODE_RADIUS,
  GLOBAL_PATH_RADIUS,
  PENDING_TARGET_SCREEN_DIAMETER_PX,
  POINT_CLOUD_MIN_ORBIT_DISTANCE,
  POINT_CLOUD_PIXEL_RATIO_LIMIT,
  ROBOT_ARROW_COLOR,
  ROBOT_ARROW_HEAD_LENGTH,
  ROBOT_ARROW_HEAD_WIDTH,
  ROBOT_ARROW_LENGTH,
  ROBOT_BODY_COLOR,
  ROBOT_HEIGHT,
  ROBOT_RADIUS,
  ROBOT_SCREEN_DIAMETER_PX,
  SCAN_BODY_CYLINDER_CENTER_Z_OFFSET,
  SCAN_BODY_CYLINDER_HEIGHT,
  SCAN_BODY_CYLINDER_OFFSETS,
  SCAN_BODY_CYLINDER_RADIUS,
  WAYPOINT_ARROW_HEAD_LENGTH,
  WAYPOINT_ARROW_HEAD_WIDTH,
  WAYPOINT_ARROW_LENGTH,
  WAYPOINT_COLOR,
  WAYPOINT_LABEL_SCREEN_WIDTH_PX,
  WAYPOINT_RADIUS,
  WAYPOINT_SCREEN_DIAMETER_PX,
  applyAdaptiveOverlayScale,
  clamp,
  createMapYawDirection,
  createOrbitPivotMarker,
  createPointCloudMaterial,
  createWaypointLabelSprite,
  disposeObject3D,
  getLayerPreset,
  getAdaptiveCameraNear,
  getWallHeightGradientBounds,
  shouldShowOrbitPivotMarker,
  setMaterialDepth,
  setPointCloudViewportHeight,
  setPointCloudWallColorMode,
  softenGrid,
  type PointCloudLayer,
} from './PointCloud3DViewerUtils'

const GROUND_PICK_THRESHOLD_PX = 44
const GROUND_FALLBACK_BOUNDS_MARGIN_M = 1.0
const WALL_HEIGHT_SAMPLE_LIMIT = 4096

type Props = {
  layers?: PointCloudLayer[]
  points?: PointCloudPoints
  viewKey?: string
  waypoints: NavWaypoint[]
  fences: NavFence[]
  fencesVisible?: boolean
  robotPose: RobotPose | null
  globalPath: GlobalPath | null
  executionPath: GlobalPath | null
  mode?: 'none' | 'waypoint' | 'pose' | 'fence'
  followRobot?: boolean
  centerHeight?: number | null
  wallColorMode?: WallColorMode
  tiledScene?: PcdSceneTileManifest | null
  qualityMode?: PointCloudQualityMode
  tileVisibility?: {
    ground: boolean
    wall: boolean
    footprint_fill: boolean
  }
  onGroundPointerChange?: (pos: { x: number; y: number; z: number } | null) => void
  onAddWaypoint?: (pos: { x: number; y: number; z: number; yaw: number }) => void
  onAddFence?: (start: { x: number; y: number }, end: { x: number; y: number }) => void
  onSetPose?: (pos: { x: number; y: number; z: number; yaw: number }) => void
}

type RenderedCloudLayer = {
  bounds: THREE.Box3
  cloud: THREE.Points
  points: PointCloudPoints
  intensity?: Uint8Array
}

export function PointCloud3DViewer({
  layers,
  points,
  viewKey = 'default',
  waypoints,
  fences,
  fencesVisible = true,
  robotPose,
  globalPath,
  executionPath,
  mode = 'none',
  followRobot = false,
  centerHeight = null,
  wallColorMode = 'height',
  tiledScene = null,
  qualityMode = 'auto',
  tileVisibility = { ground: true, wall: true, footprint_fill: true },
  onGroundPointerChange,
  onAddWaypoint,
  onAddFence,
  onSetPose,
}: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [webglSupported] = useState(() => detectWebGLSupport())
  const sceneRef = useRef<THREE.Scene | null>(null)
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null)
  const controlsRef = useRef<OrbitControls | null>(null)
  const followOffsetRef = useRef<THREE.Vector3 | null>(null)
  const gridRef = useRef<THREE.GridHelper | null>(null)
  const cloudGroupRef = useRef<THREE.Group | null>(null)
  const renderedCloudLayersRef = useRef<Map<PcdSceneLayerRole, RenderedCloudLayer>>(new Map())
  const tileManagerRef = useRef<PointCloudTileManager | null>(null)
  const invalidateRenderRef = useRef<() => void>(() => undefined)
  const wallColorModeRef = useRef(wallColorMode)
  const qualityModeRef = useRef(qualityMode)
  const tileVisibilityRef = useRef(tileVisibility)
  const pathGroupRef = useRef<THREE.Group | null>(null)
  const waypointGroupRef = useRef<THREE.Group | null>(null)
  const fenceGroupRef = useRef<THREE.Group | null>(null)
  const pendingGroupRef = useRef<THREE.Group | null>(null)
  const robotGroupRef = useRef<THREE.Group | null>(null)
  const scanBodyGroupRef = useRef<THREE.Group | null>(null)
  const orbitPivotMarkerRef = useRef<THREE.Group | null>(null)
  const orbitPivotAvailableRef = useRef(false)
  const lastAutoFitViewKeyRef = useRef<string | null>(null)
  const pendingTargetRef = useRef<{
    x: number
    y: number
    z: number
    yaw: number
  } | null>(null)
  const [pendingTarget, setPendingTarget] = useState<{
    x: number
    y: number
    z: number
    yaw: number
  } | null>(null)
  const [pendingFenceStart, setPendingFenceStart] = useState<{ x: number; y: number; z: number } | null>(null)
  const pendingFenceStartRef = useRef<{ x: number; y: number; z: number } | null>(null)
  const [fenceCursor, setFenceCursor] = useState<{ x: number; y: number; z: number } | null>(null)
  const [fenceDraftMode, setFenceDraftMode] = useState(mode)
  const [tileStats, setTileStats] = useState<PointCloudTileStats | null>(null)

  if (fenceDraftMode !== mode) {
    setFenceDraftMode(mode)
    setPendingFenceStart(null)
    setFenceCursor(null)
  }

  useEffect(() => {
    pendingFenceStartRef.current = pendingFenceStart
  }, [pendingFenceStart])

  const normalizedLayers: PointCloudLayer[] = useMemo(
    () => {
      const sourceLayers = layers?.length
        ? layers
        : points && points.length > 0
          ? [{ role: 'ground' as const, points }]
          : []

      return sourceLayers
    },
    [layers, points],
  )
  const groundPreviewBounds = useMemo(() => {
    const tiledGroundBounds = tiledScene?.layer_bounds.ground
    if (tiledGroundBounds) {
      return {
        minX: tiledGroundBounds.min_x,
        maxX: tiledGroundBounds.max_x,
        minY: tiledGroundBounds.min_y,
        maxY: tiledGroundBounds.max_y,
        centerZ: (tiledGroundBounds.min_z + tiledGroundBounds.max_z) / 2,
      }
    }
    const groundLayers = normalizedLayers.filter((layer) => layer.role === 'ground')
    if (groundLayers.length === 0) return null

    let minX = Number.POSITIVE_INFINITY
    let maxX = Number.NEGATIVE_INFINITY
    let minY = Number.POSITIVE_INFINITY
    let maxY = Number.NEGATIVE_INFINITY
    let minZ = Number.POSITIVE_INFINITY
    let maxZ = Number.NEGATIVE_INFINITY

    groundLayers.forEach((layer) => {
      const pointCount = getPointCount(layer.points)
      for (let index = 0; index < pointCount; index += 1) {
        const offset = index * 3
        const point = layer.points instanceof Float32Array ? null : layer.points[index]
        const x = layer.points instanceof Float32Array ? layer.points[offset] : point![0]
        const y = layer.points instanceof Float32Array ? layer.points[offset + 1] : point![1]
        const z = layer.points instanceof Float32Array ? layer.points[offset + 2] : point![2]
        minX = Math.min(minX, x)
        maxX = Math.max(maxX, x)
        minY = Math.min(minY, y)
        maxY = Math.max(maxY, y)
        minZ = Math.min(minZ, z)
        maxZ = Math.max(maxZ, z)
      }
    })

    if (!Number.isFinite(minX) || !Number.isFinite(minY) || !Number.isFinite(minZ)) return null
    return {
      minX,
      maxX,
      minY,
      maxY,
      centerZ: (minZ + maxZ) / 2,
    }
  }, [normalizedLayers, tiledScene?.layer_bounds.ground])
  const totalPointCount = normalizedLayers.reduce((sum, layer) => sum + getPointCount(layer.points), 0)

  useEffect(() => {
    wallColorModeRef.current = wallColorMode
  }, [wallColorMode])

  useEffect(() => {
    qualityModeRef.current = qualityMode
  }, [qualityMode])

  useEffect(() => {
    tileVisibilityRef.current = tileVisibility
  }, [tileVisibility])

  useEffect(() => {
    if (!webglSupported) return
    const host = hostRef.current
    if (!host) return

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x030506)
    sceneRef.current = scene

    const camera = new THREE.PerspectiveCamera(55, 1, 0.01, 10000)
    camera.position.set(8, 8, 8)
    camera.lookAt(0, 0, 0)
    cameraRef.current = camera

    const renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: 'high-performance' })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, POINT_CLOUD_PIXEL_RATIO_LIMIT))
    host.appendChild(renderer.domElement)
    rendererRef.current = renderer
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.08
    controls.mouseButtons = {
      LEFT: THREE.MOUSE.PAN,
      MIDDLE: THREE.MOUSE.DOLLY,
      RIGHT: THREE.MOUSE.ROTATE,
    }
    controlsRef.current = controls

    const orbitPivotMarker = createOrbitPivotMarker()
    orbitPivotMarkerRef.current = orbitPivotMarker
    scene.add(orbitPivotMarker)
    let orbitInteractionActive = false
    let renderRequested = true
    invalidateRenderRef.current = () => {
      renderRequested = true
    }
    const handleOrbitStart = () => {
      orbitInteractionActive = true
      renderRequested = true
    }
    const handleOrbitChange = () => {
      renderRequested = true
    }
    const handleOrbitEnd = () => {
      orbitInteractionActive = false
      renderRequested = true
    }
    controls.addEventListener('start', handleOrbitStart)
    controls.addEventListener('change', handleOrbitChange)
    controls.addEventListener('end', handleOrbitEnd)

    const grid = new THREE.GridHelper(80, 40, 0x33515a, 0x1d333a)
    softenGrid(grid)
    gridRef.current = grid
    scene.add(grid)
    scene.add(new THREE.AmbientLight(0xffffff, 0.85))

    const cloudGroup = new THREE.Group()
    const renderedCloudLayers = renderedCloudLayersRef.current
    cloudGroupRef.current = cloudGroup
    scene.add(cloudGroup)

    const pathGroup = new THREE.Group()
    pathGroupRef.current = pathGroup
    scene.add(pathGroup)

    const waypointGroup = new THREE.Group()
    waypointGroupRef.current = waypointGroup
    scene.add(waypointGroup)

    const fenceGroup = new THREE.Group()
    fenceGroupRef.current = fenceGroup
    scene.add(fenceGroup)

    const pendingGroup = new THREE.Group()
    pendingGroupRef.current = pendingGroup
    scene.add(pendingGroup)

    const robotGroup = new THREE.Group()
    robotGroup.visible = false
    robotGroup.renderOrder = 90
    const halo = new THREE.Mesh(
      new THREE.RingGeometry(ROBOT_RADIUS * 1.15, ROBOT_RADIUS * 1.75, 32),
      new THREE.MeshBasicMaterial({
        color: ROBOT_BODY_COLOR,
        transparent: true,
        opacity: 0.32,
        side: THREE.DoubleSide,
        depthTest: false,
        depthWrite: false,
      }),
    )
    halo.rotation.x = -Math.PI / 2
    halo.position.y = 0.012
    halo.renderOrder = 79
    robotGroup.add(halo)

    const body = new THREE.Mesh(
      new THREE.CylinderGeometry(ROBOT_RADIUS, ROBOT_RADIUS, ROBOT_HEIGHT, 24),
      new THREE.MeshBasicMaterial({
        color: ROBOT_BODY_COLOR,
        transparent: true,
        opacity: 1,
        depthTest: false,
        depthWrite: false,
      }),
    )
    body.position.y = ROBOT_HEIGHT / 2
    body.renderOrder = 90
    robotGroup.add(body)

    const direction = new THREE.ArrowHelper(
      new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(0, ROBOT_HEIGHT + 0.06, 0),
      ROBOT_ARROW_LENGTH,
      ROBOT_ARROW_COLOR,
      ROBOT_ARROW_HEAD_LENGTH,
      ROBOT_ARROW_HEAD_WIDTH,
    )
    setMaterialDepth(direction.line.material, false, false, true)
    setMaterialDepth(direction.cone.material, false, false, true)
    direction.renderOrder = 91
    robotGroup.add(direction)
    robotGroup.userData.adaptiveScale = {
      pixels: ROBOT_SCREEN_DIAMETER_PX,
      baseSize: ROBOT_RADIUS * 2,
      minScale: 0.05,
      maxScale: 120,
    }
    robotGroupRef.current = robotGroup
    scene.add(robotGroup)

    // Physical SCAN collision body.  Unlike the orange UI marker above this
    // group is intentionally not adaptively scaled: its physical radii must
    // remain comparable with walls, paths and point-cloud geometry.
    const scanBodyGroup = new THREE.Group()
    scanBodyGroup.visible = false
    const scanBodyColors = [0x22d3ee, 0xa78bfa]
    SCAN_BODY_CYLINDER_OFFSETS.forEach((offset, index) => {
      const cylinderGroup = new THREE.Group()
      cylinderGroup.position.x = offset

      const geometry = new THREE.CylinderGeometry(
        SCAN_BODY_CYLINDER_RADIUS,
        SCAN_BODY_CYLINDER_RADIUS,
        SCAN_BODY_CYLINDER_HEIGHT,
        48,
      )
      const bodyMesh = new THREE.Mesh(
        geometry,
        new THREE.MeshBasicMaterial({
          color: scanBodyColors[index],
          transparent: true,
          opacity: 0.18,
          depthTest: false,
          depthWrite: false,
          side: THREE.DoubleSide,
        }),
      )
      bodyMesh.position.y = SCAN_BODY_CYLINDER_CENTER_Z_OFFSET
      bodyMesh.renderOrder = 84
      cylinderGroup.add(bodyMesh)

      const outline = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry),
        new THREE.LineBasicMaterial({
          color: scanBodyColors[index],
          transparent: true,
          opacity: 0.95,
          depthTest: false,
          depthWrite: false,
        }),
      )
      outline.position.y = SCAN_BODY_CYLINDER_CENTER_Z_OFFSET
      outline.renderOrder = 85
      cylinderGroup.add(outline)
      scanBodyGroup.add(cylinderGroup)
    })
    scanBodyGroupRef.current = scanBodyGroup
    scene.add(scanBodyGroup)

    const resize = () => {
      const rect = host.getBoundingClientRect()
      const width = Math.max(1, rect.width)
      const height = Math.max(1, rect.height)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      renderer.setSize(width, height, false)
      const drawingBufferSize = renderer.getDrawingBufferSize(new THREE.Vector2())
      renderedCloudLayers.forEach((rendered) => {
        setPointCloudViewportHeight(rendered.cloud.material, drawingBufferSize.y)
      })
      tileManagerRef.current?.setViewportHeight(drawingBufferSize.y)
      renderRequested = true
    }

    const resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(host)
    resize()

    let animationId = 0
    let lastRenderAt = 0
    const animate = (now: number) => {
      const controlsChanged = controls.update()
      const moving = orbitInteractionActive || controlsChanged
      tileManagerRef.current?.update(moving, now)
      waypointGroup.traverse((object) => applyAdaptiveOverlayScale(object, camera, renderer))
      pendingGroup.traverse((object) => applyAdaptiveOverlayScale(object, camera, renderer))
      applyAdaptiveOverlayScale(robotGroup, camera, renderer)
      orbitPivotMarker.position.copy(controls.target)
      applyAdaptiveOverlayScale(orbitPivotMarker, camera, renderer)
      // 旋转中心只在相机交互或阻尼运动期间显示，停止后立即隐藏。
      orbitPivotMarker.visible = shouldShowOrbitPivotMarker(
        orbitPivotAvailableRef.current,
        moving,
      )
      const orbitDistance = camera.position.distanceTo(controls.target)
      const adaptiveNear = getAdaptiveCameraNear(orbitDistance)
      if (Math.abs(camera.near - adaptiveNear) > Math.max(0.0005, camera.near * 0.05)) {
        camera.near = adaptiveNear
        camera.updateProjectionMatrix()
      }
      const targetInterval = moving ? 1000 / 30 : 1000 / 10
      if (renderRequested || now - lastRenderAt >= targetInterval) {
        renderer.setRenderTarget(null)
        renderer.render(scene, camera)
        lastRenderAt = now
        renderRequested = false
      }
      animationId = requestAnimationFrame(animate)
    }
    animationId = requestAnimationFrame(animate)

    return () => {
      cancelAnimationFrame(animationId)
      resizeObserver.disconnect()
      controls.removeEventListener('start', handleOrbitStart)
      controls.removeEventListener('change', handleOrbitChange)
      controls.removeEventListener('end', handleOrbitEnd)
      controls.dispose()
      cloudGroup.children.forEach(disposeObject3D)
      cloudGroup.clear()
      renderedCloudLayers.clear()
      pathGroup.children.forEach(disposeObject3D)
      pathGroup.clear()
      waypointGroup.children.forEach(disposeObject3D)
      waypointGroup.clear()
      fenceGroup.children.forEach(disposeObject3D)
      fenceGroup.clear()
      pendingGroup.children.forEach(disposeObject3D)
      pendingGroup.clear()
      robotGroup.children.forEach(disposeObject3D)
      scanBodyGroup.children.forEach(disposeObject3D)
      scanBodyGroup.clear()
      orbitPivotMarker.children.forEach(disposeObject3D)
      orbitPivotMarker.clear()
      invalidateRenderRef.current = () => undefined
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [webglSupported])

  useEffect(() => {
    if (!webglSupported) return
    const camera = cameraRef.current
    const renderer = rendererRef.current
    const cloudGroup = cloudGroupRef.current
    tileManagerRef.current?.dispose()
    tileManagerRef.current = null
    if (!tiledScene || !camera || !renderer || !cloudGroup) {
      queueMicrotask(() => setTileStats(null))
      return
    }

    const currentVisibility = tileVisibilityRef.current
    const visibleRoles = new Set<Extract<PcdSceneLayerRole, 'ground' | 'wall' | 'footprint_fill'>>()
    if (currentVisibility.ground) visibleRoles.add('ground')
    if (currentVisibility.wall) visibleRoles.add('wall')
    if (currentVisibility.footprint_fill) visibleRoles.add('footprint_fill')
    const manager = new PointCloudTileManager({
      manifest: tiledScene,
      camera,
      renderer,
      group: cloudGroup,
      wallColorMode: wallColorModeRef.current,
      qualityMode: qualityModeRef.current,
      visibleRoles,
      onStats: (stats) => queueMicrotask(() => setTileStats(stats)),
      onInvalidate: () => invalidateRenderRef.current(),
    })
    tileManagerRef.current = manager
    invalidateRenderRef.current()
    return () => {
      manager.dispose()
      if (tileManagerRef.current === manager) tileManagerRef.current = null
    }
  }, [tiledScene, webglSupported])

  useEffect(() => {
    tileManagerRef.current?.setWallColorMode(wallColorMode)
  }, [wallColorMode])

  useEffect(() => {
    tileManagerRef.current?.setQualityMode(qualityMode)
  }, [qualityMode])

  useEffect(() => {
    const roles = new Set<Extract<PcdSceneLayerRole, 'ground' | 'wall' | 'footprint_fill'>>()
    if (tileVisibility.ground) roles.add('ground')
    if (tileVisibility.wall) roles.add('wall')
    if (tileVisibility.footprint_fill) roles.add('footprint_fill')
    tileManagerRef.current?.setVisibleRoles(roles)
  }, [tileVisibility.footprint_fill, tileVisibility.ground, tileVisibility.wall])

  useEffect(() => {
    if (!webglSupported || !tiledScene) return
    const camera = cameraRef.current
    const controls = controlsRef.current
    const grid = gridRef.current
    if (!camera || !controls) return
    const bounds = tiledScene.bounds
    const unionBox = new THREE.Box3(
      new THREE.Vector3(bounds.min_x, bounds.min_z, -bounds.max_y),
      new THREE.Vector3(bounds.max_x, bounds.max_z, -bounds.min_y),
    )
    const size = unionBox.getSize(new THREE.Vector3())
    const center = unionBox.getCenter(new THREE.Vector3())
    const targetHeight = Number.isFinite(centerHeight ?? Number.NaN) ? (centerHeight as number) : center.y
    const horizontalSpan = Math.max(size.x, size.z, 1)
    const verticalSpan = Math.max(size.y, 0.8)
    const fitHeightDistance = verticalSpan / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2))
    const fitWidthDistance = horizontalSpan / (
      2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * Math.max(camera.aspect, 0.75)
    )
    const distance = Math.max(fitHeightDistance, fitWidthDistance) * 1.22
    const autoFitKey = `${viewKey}:tiles:${tiledScene.scene_id}:${tiledScene.version}`
    controls.minDistance = POINT_CLOUD_MIN_ORBIT_DISTANCE
    if (lastAutoFitViewKeyRef.current !== autoFitKey) {
      const direction = new THREE.Vector3(1, 0.75, 1).normalize()
      controls.target.copy(center)
      controls.target.y = targetHeight
      camera.position.copy(controls.target.clone().add(direction.multiplyScalar(distance)))
      controls.maxDistance = Math.max(10, distance * 8)
      camera.near = getAdaptiveCameraNear(distance)
      camera.far = Math.max(camera.far, 1000, distance * 30)
      camera.updateProjectionMatrix()
      controls.update()
      lastAutoFitViewKeyRef.current = autoFitKey
      if (grid) {
        const gridSize = clamp(Math.ceil(horizontalSpan * 1.6), 20, 240)
        const divisions = clamp(Math.ceil(gridSize / 3), 10, 80)
        grid.geometry.dispose()
        grid.geometry = new THREE.GridHelper(gridSize, divisions, 0x33515a, 0x1d333a).geometry
        grid.position.set(center.x, targetHeight, center.z)
        softenGrid(grid)
      }
    }
    orbitPivotAvailableRef.current = true
    invalidateRenderRef.current()
  }, [centerHeight, tiledScene, viewKey, webglSupported])

  useEffect(() => {
    if (!webglSupported) return
    const scene = sceneRef.current
    const camera = cameraRef.current
    const controls = controlsRef.current
    const grid = gridRef.current
    const cloudGroup = cloudGroupRef.current
    const orbitPivotMarker = orbitPivotMarkerRef.current
    const renderer = rendererRef.current
    if (!scene || !camera || !controls || !cloudGroup || !renderer) return

    const renderedLayers = renderedCloudLayersRef.current
    const activeRoles = new Set(
      normalizedLayers
        .filter((layer) => getPointCount(layer.points) > 0)
        .map((layer) => layer.role),
    )
    renderedLayers.forEach((rendered, role) => {
      if (activeRoles.has(role)) return
      cloudGroup.remove(rendered.cloud)
      disposeObject3D(rendered.cloud)
      renderedLayers.delete(role)
    })

    if (normalizedLayers.length === 0) {
      if (!tiledScene) {
        orbitPivotAvailableRef.current = false
        if (orbitPivotMarker) orbitPivotMarker.visible = false
        lastAutoFitViewKeyRef.current = null
      }
      return
    }

    const unionBox = new THREE.Box3()
    let hasPoints = false

    normalizedLayers.forEach((layer) => {
      const pointCount = getPointCount(layer.points)
      if (pointCount === 0) return

      let rendered = renderedLayers.get(layer.role)
      if (!rendered || rendered.points !== layer.points || rendered.intensity !== layer.intensity) {
        if (rendered) {
          cloudGroup.remove(rendered.cloud)
          disposeObject3D(rendered.cloud)
        }

        const positions = new Float32Array(pointCount * 3)
        const layerBox = new THREE.Box3()
        const sampledWallHeights: number[] = []
        const wallHeightSampleStride = layer.role === 'wall'
          ? Math.max(1, Math.ceil(pointCount / WALL_HEIGHT_SAMPLE_LIMIT))
          : 0
        for (let index = 0; index < pointCount; index += 1) {
          const offset = index * 3
          const point = layer.points instanceof Float32Array ? null : layer.points[index]
          const x = layer.points instanceof Float32Array ? layer.points[offset] : point![0]
          const y = layer.points instanceof Float32Array ? layer.points[offset + 1] : point![1]
          const z = layer.points instanceof Float32Array ? layer.points[offset + 2] : point![2]
          if (wallHeightSampleStride > 0 && index % wallHeightSampleStride === 0) {
            sampledWallHeights.push(z)
          }
          // map -> Three.js: (x, y, z) => (x, z, -y)。直接写 typed array
          // 并更新包围盒，避免为每个点创建临时对象。
          const threeZ = -y
          positions[offset] = x
          positions[offset + 1] = z
          positions[offset + 2] = threeZ
          layerBox.min.x = Math.min(layerBox.min.x, x)
          layerBox.min.y = Math.min(layerBox.min.y, z)
          layerBox.min.z = Math.min(layerBox.min.z, threeZ)
          layerBox.max.x = Math.max(layerBox.max.x, x)
          layerBox.max.y = Math.max(layerBox.max.y, z)
          layerBox.max.z = Math.max(layerBox.max.z, threeZ)
        }

        const geometry = new THREE.BufferGeometry()
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
        const hasIntensity = layer.role === 'wall'
          && layer.intensity instanceof Uint8Array
          && layer.intensity.length === pointCount
        if (hasIntensity) {
          geometry.setAttribute('intensity', new THREE.Uint8BufferAttribute(layer.intensity!, 1, true))
        }
        geometry.boundingBox = layerBox.clone()
        geometry.computeBoundingSphere()

        const preset = getLayerPreset(layer.role)
        const heightGradientBounds = layer.role === 'wall'
          ? getWallHeightGradientBounds(sampledWallHeights, layerBox.min.y, layerBox.max.y)
          : { min: layerBox.min.y, max: layerBox.max.y }
        const material = createPointCloudMaterial(
          preset,
          Math.min(window.devicePixelRatio || 1, POINT_CLOUD_PIXEL_RATIO_LIMIT),
          {
            minHeight: heightGradientBounds.min,
            maxHeight: heightGradientBounds.max,
            wallColorMode,
            viewportHeight: renderer.domElement.height,
            hasIntensity,
          },
        )

        const cloud = new THREE.Points(geometry, material)
        cloud.renderOrder = preset.renderOrder
        cloud.userData.role = layer.role
        cloudGroup.add(cloud)
        rendered = { bounds: layerBox, cloud, points: layer.points, intensity: layer.intensity }
        renderedLayers.set(layer.role, rendered)
      }

      if (layer.role === 'wall') {
        setPointCloudWallColorMode(rendered.cloud.material, wallColorMode)
      }

      if (!hasPoints) {
        unionBox.copy(rendered.bounds)
        hasPoints = true
      } else {
        unionBox.union(rendered.bounds)
      }
    })

    if (!hasPoints) {
      // 瓦片模式的点云由 PointCloudTileManager 管理，不在 renderedLayers 中。
      // 此处不能用空的预览层覆盖 tiledScene effect 已设置的旋转中心状态。
      if (!tiledScene) {
        orbitPivotAvailableRef.current = false
        if (orbitPivotMarker) orbitPivotMarker.visible = false
        lastAutoFitViewKeyRef.current = null
      }
      return
    }

    orbitPivotAvailableRef.current = true

    const size = unionBox.getSize(new THREE.Vector3())
    const center = unionBox.getCenter(new THREE.Vector3())
    const targetHeight = Number.isFinite(centerHeight ?? Number.NaN) ? (centerHeight as number) : center.y
    const horizontalSpan = Math.max(size.x, size.z, 1)
    const verticalSpan = Math.max(size.y, 0.8)
    const fitHeightDistance = verticalSpan / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2))
    const fitWidthDistance = horizontalSpan / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * Math.max(camera.aspect, 0.75))
    const distance = Math.max(fitHeightDistance, fitWidthDistance) * 1.22
    const direction = new THREE.Vector3(1, 0.75, 1).normalize()

    const autoFitKey = viewKey.startsWith('mapping:')
      ? viewKey
      : [
          viewKey,
          totalPointCount,
          unionBox.min.x.toFixed(2),
          unionBox.min.y.toFixed(2),
          unionBox.min.z.toFixed(2),
          unionBox.max.x.toFixed(2),
          unionBox.max.y.toFixed(2),
          unionBox.max.z.toFixed(2),
        ].join(':')
    const shouldAutoFit = lastAutoFitViewKeyRef.current !== autoFitKey
    controls.minDistance = POINT_CLOUD_MIN_ORBIT_DISTANCE
    if (shouldAutoFit) {
      controls.target.copy(center)
      controls.target.y = targetHeight
      camera.position.copy(controls.target.clone().add(direction.multiplyScalar(distance)))
      controls.maxDistance = Math.max(10, distance * 8)
      lastAutoFitViewKeyRef.current = autoFitKey
    } else {
      controls.maxDistance = Math.max(controls.maxDistance, distance * 8, 10)
    }

    camera.near = getAdaptiveCameraNear(distance)
    camera.far = Math.max(camera.far, 1000, distance * 30)
    camera.updateProjectionMatrix()
    if (shouldAutoFit) {
      controls.update()
    }

    if (grid && shouldAutoFit) {
      const gridSize = clamp(Math.ceil(horizontalSpan * 1.6), 20, 240)
      const divisions = clamp(Math.ceil(gridSize / 3), 10, 80)
      grid.geometry.dispose()
      grid.geometry = new THREE.GridHelper(gridSize, divisions, 0x33515a, 0x1d333a).geometry
      grid.position.set(center.x, targetHeight, center.z)
      softenGrid(grid)
    }
  }, [centerHeight, normalizedLayers, tiledScene, totalPointCount, viewKey, wallColorMode, webglSupported])

  useEffect(() => {
    if (!webglSupported) return
    const scene = sceneRef.current
    const pathGroup = pathGroupRef.current
    if (!scene || !pathGroup) return

    pathGroup.children.forEach(disposeObject3D)
    pathGroup.clear()

    const zLift = 0.03

    if (globalPath && globalPath.frame_id === 'map' && globalPath.points.length >= 2) {
      const pathPoints = globalPath.points.map((point) => {
        const converted = mapToThree(point.x, point.y, point.z)
        return new THREE.Vector3(converted.x, converted.y + zLift, converted.z)
      })
      const curve = new THREE.CatmullRomCurve3(pathPoints, false, 'centripetal')
      const tubularSegments = Math.max(8, Math.min(pathPoints.length * 2, 480))
      const geometry = new THREE.TubeGeometry(curve, tubularSegments, GLOBAL_PATH_RADIUS, 8, false)
      const material = new THREE.MeshBasicMaterial({
        color: 0xfacc15,
        transparent: true,
        opacity: 0.68,
        depthTest: true,
        depthWrite: false,
      })
      const pathMesh = new THREE.Mesh(geometry, material)
      pathMesh.renderOrder = 12
      pathGroup.add(pathMesh)

      const markerStride = Math.max(1, Math.ceil(globalPath.points.length / 80))
      globalPath.points.forEach((point, index) => {
        const isTarget = index === globalPath.points.length - 1
        if (!isTarget && index % markerStride !== 0) return
        const converted = mapToThree(point.x, point.y, point.z)
        const marker = new THREE.Mesh(
          new THREE.SphereGeometry(isTarget ? GLOBAL_PATH_NODE_RADIUS * 1.5 : GLOBAL_PATH_NODE_RADIUS, 16, 10),
          new THREE.MeshBasicMaterial({
            color: isTarget ? 0x22c55e : 0xfacc15,
            transparent: true,
            opacity: 0.82,
            depthTest: true,
            depthWrite: false,
          }),
        )
        marker.position.set(converted.x, converted.y + zLift, converted.z)
        marker.renderOrder = 13
        pathGroup.add(marker)
      })
    }

    if (executionPath && executionPath.frame_id === 'map' && executionPath.points.length >= 2) {
      const executionPoints = executionPath.points.map((point) => {
        const converted = mapToThree(point.x, point.y, point.z)
        return new THREE.Vector3(converted.x, converted.y + zLift * 2, converted.z)
      })
      const geometry = new THREE.BufferGeometry().setFromPoints(executionPoints)
      const material = new THREE.LineBasicMaterial({
        color: 0x22d3ee,
        transparent: true,
        opacity: 1,
        depthTest: false,
        depthWrite: false,
      })
      const line = new THREE.Line(geometry, material)
      line.renderOrder = 20
      pathGroup.add(line)

      const markerStride = Math.max(1, Math.ceil(executionPath.points.length / 60))
      executionPath.points.forEach((point, index) => {
        const isEnd = index === executionPath.points.length - 1
        if (!isEnd && index % markerStride !== 0) return
        const converted = mapToThree(point.x, point.y, point.z)
        const marker = new THREE.Mesh(
          new THREE.SphereGeometry(isEnd ? GLOBAL_PATH_NODE_RADIUS * 1.7 : GLOBAL_PATH_NODE_RADIUS * 1.15, 14, 9),
          new THREE.MeshBasicMaterial({
            color: isEnd ? 0xf472b6 : 0x22d3ee,
            transparent: true,
            opacity: 1,
            depthTest: false,
            depthWrite: false,
          }),
        )
        marker.position.set(converted.x, converted.y + zLift * 2, converted.z)
        marker.renderOrder = 21
        pathGroup.add(marker)
      })
    }

    return () => {
      pathGroup.children.forEach(disposeObject3D)
      pathGroup.clear()
    }
  }, [executionPath, globalPath, webglSupported])

  useEffect(() => {
    if (!webglSupported) return
    const group = waypointGroupRef.current
    if (!group) return

    group.children.forEach(disposeObject3D)
    group.clear()

    waypoints.forEach((waypoint) => {
      const pos = mapToThree(waypoint.x, waypoint.y, waypoint.z)
      const marker = new THREE.Group()
      marker.position.set(pos.x, pos.y, pos.z)
      marker.renderOrder = 42
      marker.userData.adaptiveScale = {
        pixels: WAYPOINT_SCREEN_DIAMETER_PX,
        baseSize: WAYPOINT_RADIUS * 2,
        minScale: 0.05,
        maxScale: 120,
      }

      const sphere = new THREE.Mesh(
        new THREE.SphereGeometry(WAYPOINT_RADIUS, 24, 16),
        new THREE.MeshBasicMaterial({ color: WAYPOINT_COLOR }),
      )
      sphere.position.set(0, WAYPOINT_RADIUS, 0)
      sphere.renderOrder = 42
      marker.add(sphere)

      const arrow = new THREE.ArrowHelper(
        createMapYawDirection(waypoint.yaw),
        new THREE.Vector3(0, WAYPOINT_RADIUS, 0),
        WAYPOINT_ARROW_LENGTH,
        WAYPOINT_COLOR,
        WAYPOINT_ARROW_HEAD_LENGTH,
        WAYPOINT_ARROW_HEAD_WIDTH,
      )
      arrow.renderOrder = 43
      marker.add(arrow)
      group.add(marker)

      const label = createWaypointLabelSprite(waypoint.name)
      if (label) {
        label.position.set(pos.x, pos.y + WAYPOINT_RADIUS * 2.15, pos.z)
        label.renderOrder = 38
        label.userData.adaptiveSprite = {
          pixels: WAYPOINT_LABEL_SCREEN_WIDTH_PX,
          baseWidth: label.scale.x,
          baseScale: label.scale.clone(),
          minScale: 0.05,
          maxScale: 120,
        }
        group.add(label)
      }
    })
  }, [waypoints, webglSupported])

  useEffect(() => {
    if (!webglSupported) return
    const group = fenceGroupRef.current
    if (!group) return
    group.children.forEach(disposeObject3D)
    group.clear()
    if (!fencesVisible) return

    const displayZ = centerHeight ?? groundPreviewBounds?.centerZ ?? 0
    fences.forEach((fence) => {
      const start = mapToThree(fence.start.x, fence.start.y, displayZ + 0.08)
      const end = mapToThree(fence.end.x, fence.end.y, displayZ + 0.08)
      const color = fence.enabled ? 0xef4444 : 0x7f1d1d
      const geometry = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(start.x, start.y, start.z),
        new THREE.Vector3(end.x, end.y, end.z),
      ])
      const line = new THREE.Line(
        geometry,
        new THREE.LineBasicMaterial({ color, transparent: true, opacity: fence.enabled ? 1 : 0.45, depthTest: false }),
      )
      line.renderOrder = 52
      group.add(line)
      for (const point of [start, end]) {
        const marker = new THREE.Mesh(
          new THREE.SphereGeometry(0.09, 14, 10),
          new THREE.MeshBasicMaterial({ color, depthTest: false }),
        )
        marker.position.set(point.x, point.y, point.z)
        marker.renderOrder = 53
        group.add(marker)
      }
    })
  }, [centerHeight, fences, fencesVisible, groundPreviewBounds?.centerZ, webglSupported])

  useEffect(() => {
    if (!webglSupported) return
    const group = pendingGroupRef.current
    if (!group) return

    group.children.forEach(disposeObject3D)
    group.clear()

    if (mode === 'fence') {
      if (!pendingFenceStart) return
      const start = mapToThree(pendingFenceStart.x, pendingFenceStart.y, pendingFenceStart.z + 0.1)
      const cursor = fenceCursor ?? pendingFenceStart
      const end = mapToThree(cursor.x, cursor.y, cursor.z + 0.1)
      const geometry = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(start.x, start.y, start.z),
        new THREE.Vector3(end.x, end.y, end.z),
      ])
      const line = new THREE.Line(
        geometry,
        new THREE.LineDashedMaterial({ color: 0xf87171, dashSize: 0.25, gapSize: 0.15, depthTest: false }),
      )
      line.computeLineDistances()
      line.renderOrder = 62
      group.add(line)
      for (const point of [start, end]) {
        const marker = new THREE.Mesh(
          new THREE.SphereGeometry(0.12, 16, 10),
          new THREE.MeshBasicMaterial({ color: 0xf87171, depthTest: false }),
        )
        marker.position.set(point.x, point.y, point.z)
        marker.renderOrder = 63
        group.add(marker)
      }
      return
    }

    if (!pendingTarget || mode === 'none') return

    const pos = mapToThree(pendingTarget.x, pendingTarget.y, pendingTarget.z)
    const marker = new THREE.Group()
    marker.position.set(pos.x, pos.y, pos.z)
    marker.renderOrder = 60
    marker.userData.adaptiveScale = {
      pixels: PENDING_TARGET_SCREEN_DIAMETER_PX,
      baseSize: 0.48,
      minScale: 0.05,
      maxScale: 120,
    }

    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(0.24, 22, 14),
      new THREE.MeshBasicMaterial({ color: 0x22c55e }),
    )
    sphere.position.set(0, 0.24, 0)
    sphere.renderOrder = 60
    marker.add(sphere)

    const arrow = new THREE.ArrowHelper(
      createMapYawDirection(pendingTarget.yaw),
      new THREE.Vector3(0, 0.24, 0),
      1.0,
      0x86efac,
      0.32,
      0.2,
    )
    arrow.renderOrder = 61
    marker.add(arrow)
    group.add(marker)
  }, [fenceCursor, mode, pendingFenceStart, pendingTarget, webglSupported])

  useEffect(() => {
    if (!webglSupported) return
    const controls = controlsRef.current
    if (!controls) return

    controls.enabled = mode === 'none'
    controls.enablePan = !followRobot
    controls.update()

    return () => {
      controls.enabled = true
      controls.enablePan = true
    }
  }, [followRobot, mode, webglSupported])

  useEffect(() => {
    if (!webglSupported) return
    const robotGroup = robotGroupRef.current
    const scanBodyGroup = scanBodyGroupRef.current
    const camera = cameraRef.current
    const controls = controlsRef.current
    if (!robotGroup || !scanBodyGroup || !camera || !controls) return

    if (!robotPose) {
      robotGroup.visible = false
      scanBodyGroup.visible = false
      return
    }

    const pos = mapToThree(robotPose.x, robotPose.y, robotPose.z)
    robotGroup.visible = true
    robotGroup.position.set(pos.x, pos.y, pos.z)
    robotGroup.rotation.y = robotPose.yaw
    scanBodyGroup.visible = robotPose.frame_id === 'map'
    scanBodyGroup.position.set(pos.x, pos.y, pos.z)
    scanBodyGroup.rotation.y = robotPose.yaw

    if (followRobot) {
      const currentTarget = controls.target.clone()
      const currentOffset = camera.position.clone().sub(currentTarget)
      followOffsetRef.current = currentOffset
      controls.target.set(pos.x, pos.y, pos.z)
      camera.position.copy(new THREE.Vector3(pos.x, pos.y, pos.z).add(followOffsetRef.current))
      controls.update()
    } else {
      followOffsetRef.current = null
    }
  }, [followRobot, robotPose, webglSupported])

  const readGroundPlanePoint = (event: PointerEvent<HTMLDivElement>) => {
    const host = hostRef.current
    const camera = cameraRef.current
    if (!host || !camera || !groundPreviewBounds) return null

    const rect = host.getBoundingClientRect()
    const ndc = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -(((event.clientY - rect.top) / rect.height) * 2 - 1),
    )
    const raycaster = new THREE.Raycaster()
    raycaster.setFromCamera(ndc, camera)
    const planeZ = centerHeight ?? groundPreviewBounds.centerZ
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -planeZ)
    const hit = new THREE.Vector3()
    if (!raycaster.ray.intersectPlane(plane, hit)) return null

    const mapPoint = threeToMap(hit.x, hit.y, hit.z)
    const margin = GROUND_FALLBACK_BOUNDS_MARGIN_M
    if (
      mapPoint.x < groundPreviewBounds.minX - margin ||
      mapPoint.x > groundPreviewBounds.maxX + margin ||
      mapPoint.y < groundPreviewBounds.minY - margin ||
      mapPoint.y > groundPreviewBounds.maxY + margin
    ) {
      return null
    }

    return {
      x: mapPoint.x,
      y: mapPoint.y,
      z: planeZ,
    }
  }

  const readGroundPoint = (event: PointerEvent<HTMLDivElement>) => {
    const host = hostRef.current
    const camera = cameraRef.current
    const cloudGroup = cloudGroupRef.current
    if (!host || !camera || !cloudGroup) return null

    const groundObjects = cloudGroup.children.filter((child) => child.userData.role === 'ground')
    if (groundObjects.length === 0) return null

    const rect = host.getBoundingClientRect()
    const pointerX = event.clientX - rect.left
    const pointerY = event.clientY - rect.top
    const worldPoint = new THREE.Vector3()
    const screenPoint = new THREE.Vector3()
    let bestPoint: THREE.Vector3 | null = null
    let bestDistanceSq = GROUND_PICK_THRESHOLD_PX * GROUND_PICK_THRESHOLD_PX

    groundObjects.forEach((object) => {
      if (!(object instanceof THREE.Points)) return
      const position = object.geometry.getAttribute('position')
      if (!position) return

      object.updateMatrixWorld()
      for (let index = 0; index < position.count; index += 1) {
        worldPoint.fromBufferAttribute(position, index).applyMatrix4(object.matrixWorld)
        screenPoint.copy(worldPoint).project(camera)
        if (screenPoint.z < -1 || screenPoint.z > 1) continue

        const screenX = (screenPoint.x * 0.5 + 0.5) * rect.width
        const screenY = (-screenPoint.y * 0.5 + 0.5) * rect.height
        const distanceSq = (screenX - pointerX) ** 2 + (screenY - pointerY) ** 2
        if (distanceSq <= bestDistanceSq) {
          bestDistanceSq = distanceSq
          bestPoint = worldPoint.clone()
        }
      }
    })

    const pickedPoint = bestPoint as THREE.Vector3 | null
    if (!pickedPoint) return readGroundPlanePoint(event)

    const mapPoint = threeToMap(pickedPoint.x, pickedPoint.y, pickedPoint.z)
    return {
      x: mapPoint.x,
      y: mapPoint.y,
      z: mapPoint.z,
    }
  }

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (mode === 'none') return
    event.preventDefault()
    const point = readGroundPoint(event)
    onGroundPointerChange?.(point)
    if (!point) return
    event.currentTarget.setPointerCapture(event.pointerId)
    const nextTarget = {
      ...point,
      yaw: 0,
    }
    pendingTargetRef.current = nextTarget
    setPendingTarget(nextTarget)
  }

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (mode === 'none') return
    event.preventDefault()
    const point = readGroundPoint(event)
    onGroundPointerChange?.(point)
    if (!point) return
    if (mode === 'fence') {
      setFenceCursor(point)
    }
    setPendingTarget((current) => {
      if (!current) return current
      const dx = point.x - current.x
      const dy = point.y - current.y
      const yaw = Math.abs(dx) < 0.0001 && Math.abs(dy) < 0.0001
        ? current.yaw
        : Math.atan2(dy, dx)
      const nextTarget = { ...current, yaw }
      pendingTargetRef.current = nextTarget
      return nextTarget
    })
  }

  const handlePointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (mode === 'none') return
    event.preventDefault()
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    const target = pendingTargetRef.current
    if (!target) return

    if (mode === 'fence') {
      const next = advanceFenceDraft(
        pendingFenceStartRef.current,
        { x: target.x, y: target.y, z: target.z },
      )
      if (next.completed) {
        onAddFence?.(
          { x: next.completed.start.x, y: next.completed.start.y },
          { x: next.completed.end.x, y: next.completed.end.y },
        )
        setFenceCursor(null)
      } else if (pendingFenceStartRef.current === null && next.start) {
        setFenceCursor(next.start)
      }
      pendingFenceStartRef.current = next.start
      setPendingFenceStart(next.start)
    } else if (mode === 'waypoint') {
      onAddWaypoint?.(target)
    } else {
      onSetPose?.(target)
    }
    pendingTargetRef.current = null
    setPendingTarget(null)
  }

  if (!webglSupported) {
    return (
      <div className="pcd-viewer-shell">
        <div className="pcd-viewer-label">3D 点云</div>
        <div className="flex min-h-[420px] items-center justify-center rounded-2xl border border-white/10 bg-[radial-gradient(circle_at_top,rgba(16,24,32,0.92),rgba(4,7,10,0.98))] px-6 text-center">
          <div className="max-w-2xl space-y-4">
            <div className="text-2xl font-black text-white">当前浏览器未启用 WebGL，无法渲染三维点云地图。</div>
            <div className="text-sm leading-7 text-zinc-300">
              <div>请尝试：</div>
              <div>- 使用电脑浏览器访问本页面</div>
              <div>- 在开发板 Chromium 中启用 `chrome://flags` → `Override software rendering list`</div>
              <div>- 使用启动参数 `--ignore-gpu-blocklist --enable-webgl --use-gl=egl`</div>
              <div>- 检查 `chrome://gpu` 中 WebGL/WebGL2 是否可用</div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const wallBounds = tiledScene?.layer_bounds.wall
  const intensityRange = tiledScene?.stats.wall?.intensity_percentile_2_98
  const tilePhaseLabel = tileStats?.phase === 'loading'
    ? '正在加载完整点云'
    : '完整点云已加载'

  return (
    <div className="pcd-viewer-shell">
      <div className="pcd-viewer-label">3D 点云</div>
      <div className="pcd-path-legend" aria-label="导航路径图例">
        <span><i className="is-global" />全局路径</span>
        <span><i className="is-execution" />SCAN 实际轨迹</span>
        <span><i className="is-scan-body" />B2 双圆柱 r={SCAN_BODY_CYLINDER_RADIUS.toFixed(3)}m</span>
      </div>
      {tiledScene && tileStats ? (
        <div className="pcd-tile-status" aria-live="polite">
          <strong>{tilePhaseLabel}</strong>
          <span>{tileStats.loadedPoints.toLocaleString()} / {tileStats.totalPoints.toLocaleString()} 点</span>
          <span>{(tileStats.loadedBytes / 1024 / 1024).toFixed(1)} MB已加载</span>
          <span>{qualityMode === 'auto' ? '均衡密度' : qualityMode === 'performance' ? '流畅密度' : '原始点'}</span>
        </div>
      ) : null}
      {wallColorMode !== 'solid' ? (
        <div className="pcd-color-legend" aria-label={wallColorMode === 'height' ? '高度颜色图例' : '雷达强度颜色图例'}>
          <span>{wallColorMode === 'height' ? '高度' : '雷达强度'}</span>
          <i className={wallColorMode === 'height' ? 'is-height' : 'is-intensity'} />
          <small>
            {wallColorMode === 'height'
              ? `${(wallBounds?.min_z ?? 0).toFixed(2)}m — ${(wallBounds?.max_z ?? 0).toFixed(2)}m`
              : intensityRange
                ? `${intensityRange[0].toFixed(1)} — ${intensityRange[1].toFixed(1)}`
                : '低 — 高'}
          </small>
        </div>
      ) : null}
      <div
        className={`pcd-three-host ${mode !== 'none' ? 'is-adding' : ''}`}
        ref={hostRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerLeave={() => {
          onGroundPointerChange?.(null)
        }}
        onPointerUp={handlePointerUp}
      />
      {totalPointCount === 0 && !tiledScene ? <div className="pcd-viewer-empty">等待点云预览数据</div> : null}
    </div>
  )
}
