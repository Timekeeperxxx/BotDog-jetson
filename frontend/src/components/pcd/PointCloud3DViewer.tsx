import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { NavWaypoint } from '../../types/pcdMap'
import type { GlobalPath, RobotPose, ScanExecutionPath } from '../../types/navState'
import { mapToThree, threeToMap } from '../../utils/pointCloudTransform'
import { detectWebGLSupport } from './webglSupport'
import {
  GLOBAL_PATH_NODE_RADIUS,
  GLOBAL_PATH_RADIUS,
  PENDING_TARGET_SCREEN_DIAMETER_PX,
  POINT_CLOUD_PIXEL_RATIO_LIMIT,
  ROBOT_ARROW_COLOR,
  ROBOT_ARROW_HEAD_LENGTH,
  ROBOT_ARROW_HEAD_WIDTH,
  ROBOT_ARROW_LENGTH,
  ROBOT_BODY_COLOR,
  ROBOT_HEIGHT,
  ROBOT_RADIUS,
  ROBOT_SCREEN_DIAMETER_PX,
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
  createPointCloudMaterial,
  createWaypointLabelSprite,
  disposeObject3D,
  getLayerPreset,
  limitDisplayPoints,
  setMaterialDepth,
  softenGrid,
  type PointCloudLayer,
} from './PointCloud3DViewerUtils'

const GROUND_PICK_THRESHOLD_PX = 44
const GROUND_FALLBACK_BOUNDS_MARGIN_M = 1.0

type Props = {
  layers?: PointCloudLayer[]
  points?: [number, number, number][]
  viewKey?: string
  waypoints: NavWaypoint[]
  robotPose: RobotPose | null
  globalPath: GlobalPath | null
  scanExecutionPath: ScanExecutionPath | null
  mode?: 'none' | 'waypoint' | 'pose'
  followRobot?: boolean
  centerHeight?: number | null
  onGroundPointerChange?: (pos: { x: number; y: number; z: number } | null) => void
  onAddWaypoint?: (pos: { x: number; y: number; z: number; yaw: number }) => void
  onSetPose?: (pos: { x: number; y: number; z: number; yaw: number }) => void
}

export function PointCloud3DViewer({
  layers,
  points,
  viewKey = 'default',
  waypoints,
  robotPose,
  globalPath,
  scanExecutionPath,
  mode = 'none',
  followRobot = false,
  centerHeight = null,
  onGroundPointerChange,
  onAddWaypoint,
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
  const pathGroupRef = useRef<THREE.Group | null>(null)
  const waypointGroupRef = useRef<THREE.Group | null>(null)
  const pendingGroupRef = useRef<THREE.Group | null>(null)
  const robotGroupRef = useRef<THREE.Group | null>(null)
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
  const [pathClockMs, setPathClockMs] = useState(() => Date.now())

  useEffect(() => {
    const timer = window.setInterval(() => setPathClockMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const normalizedLayers: PointCloudLayer[] = useMemo(
    () => {
      const sourceLayers = layers?.length
        ? layers
        : points && points.length > 0
          ? [{ role: 'ground' as const, points }]
          : []

      return sourceLayers.map((layer) => ({
        ...layer,
        points: limitDisplayPoints(layer.role, layer.points),
      }))
    },
    [layers, points],
  )
  const groundPreviewBounds = useMemo(() => {
    const groundLayers = normalizedLayers.filter((layer) => layer.role === 'ground')
    if (groundLayers.length === 0) return null

    let minX = Number.POSITIVE_INFINITY
    let maxX = Number.NEGATIVE_INFINITY
    let minY = Number.POSITIVE_INFINITY
    let maxY = Number.NEGATIVE_INFINITY
    let minZ = Number.POSITIVE_INFINITY
    let maxZ = Number.NEGATIVE_INFINITY

    groundLayers.forEach((layer) => {
      layer.points.forEach(([x, y, z]) => {
        minX = Math.min(minX, x)
        maxX = Math.max(maxX, x)
        minY = Math.min(minY, y)
        maxY = Math.max(maxY, y)
        minZ = Math.min(minZ, z)
        maxZ = Math.max(maxZ, z)
      })
    })

    if (!Number.isFinite(minX) || !Number.isFinite(minY) || !Number.isFinite(minZ)) return null
    return {
      minX,
      maxX,
      minY,
      maxY,
      centerZ: (minZ + maxZ) / 2,
    }
  }, [normalizedLayers])
  const totalPointCount = normalizedLayers.reduce((sum, layer) => sum + layer.points.length, 0)

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

    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
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

    const grid = new THREE.GridHelper(80, 40, 0x33515a, 0x1d333a)
    softenGrid(grid)
    gridRef.current = grid
    scene.add(grid)
    scene.add(new THREE.AmbientLight(0xffffff, 0.85))

    const cloudGroup = new THREE.Group()
    cloudGroupRef.current = cloudGroup
    scene.add(cloudGroup)

    const pathGroup = new THREE.Group()
    pathGroupRef.current = pathGroup
    scene.add(pathGroup)

    const waypointGroup = new THREE.Group()
    waypointGroupRef.current = waypointGroup
    scene.add(waypointGroup)

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

    const resize = () => {
      const rect = host.getBoundingClientRect()
      const width = Math.max(1, rect.width)
      const height = Math.max(1, rect.height)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      renderer.setSize(width, height, false)
    }

    const resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(host)
    resize()

    let animationId = 0
    const animate = () => {
      controls.update()
      waypointGroup.traverse((object) => applyAdaptiveOverlayScale(object, camera, renderer))
      pendingGroup.traverse((object) => applyAdaptiveOverlayScale(object, camera, renderer))
      applyAdaptiveOverlayScale(robotGroup, camera, renderer)
      renderer.render(scene, camera)
      animationId = requestAnimationFrame(animate)
    }
    animate()

    return () => {
      cancelAnimationFrame(animationId)
      resizeObserver.disconnect()
      controls.dispose()
      cloudGroup.children.forEach(disposeObject3D)
      cloudGroup.clear()
      pathGroup.children.forEach(disposeObject3D)
      pathGroup.clear()
      waypointGroup.children.forEach(disposeObject3D)
      waypointGroup.clear()
      pendingGroup.children.forEach(disposeObject3D)
      pendingGroup.clear()
      robotGroup.children.forEach(disposeObject3D)
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [webglSupported])

  useEffect(() => {
    if (!webglSupported) return
    const scene = sceneRef.current
    const camera = cameraRef.current
    const controls = controlsRef.current
    const grid = gridRef.current
    const cloudGroup = cloudGroupRef.current
    if (!scene || !camera || !controls || !cloudGroup) return

    cloudGroup.children.forEach(disposeObject3D)
    cloudGroup.clear()

    if (normalizedLayers.length === 0) {
      lastAutoFitViewKeyRef.current = null
      return
    }

    const unionBox = new THREE.Box3()
    let hasPoints = false

    normalizedLayers.forEach((layer) => {
      if (layer.points.length === 0) return

      const positions = new Float32Array(layer.points.length * 3)
      const layerBox = new THREE.Box3()
      layer.points.forEach(([x, y, z], index) => {
        // map -> Three.js: (x, y, z) => (x, z, -y)。直接写 typed array
        // 并更新包围盒，避免为每个点创建临时对象。
        const threeZ = -y
        positions[index * 3] = x
        positions[index * 3 + 1] = z
        positions[index * 3 + 2] = threeZ
        layerBox.min.x = Math.min(layerBox.min.x, x)
        layerBox.min.y = Math.min(layerBox.min.y, z)
        layerBox.min.z = Math.min(layerBox.min.z, threeZ)
        layerBox.max.x = Math.max(layerBox.max.x, x)
        layerBox.max.y = Math.max(layerBox.max.y, z)
        layerBox.max.z = Math.max(layerBox.max.z, threeZ)
      })

      const geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
      geometry.boundingBox = layerBox.clone()
      geometry.computeBoundingSphere()

      const preset = getLayerPreset(layer.role)
      const material = createPointCloudMaterial(
        preset,
        Math.min(window.devicePixelRatio || 1, POINT_CLOUD_PIXEL_RATIO_LIMIT),
      )

      const cloud = new THREE.Points(geometry, material)
      cloud.renderOrder = preset.renderOrder
      cloud.userData.role = layer.role
      cloudGroup.add(cloud)

      if (!hasPoints) {
        unionBox.copy(layerBox)
        hasPoints = true
      } else {
        unionBox.union(layerBox)
      }
    })

    if (!hasPoints) {
      lastAutoFitViewKeyRef.current = null
      return
    }

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
    if (shouldAutoFit) {
      controls.target.copy(center)
      controls.target.y = targetHeight
      camera.position.copy(controls.target.clone().add(direction.multiplyScalar(distance)))
      controls.minDistance = Math.max(0.5, distance * 0.2)
      controls.maxDistance = Math.max(10, distance * 8)
      lastAutoFitViewKeyRef.current = autoFitKey
    } else {
      controls.maxDistance = Math.max(controls.maxDistance, distance * 8, 10)
    }

    camera.near = Math.max(0.01, distance / 500)
    camera.far = Math.max(camera.far, 1000, distance * 30)
    camera.updateProjectionMatrix()
    if (shouldAutoFit) {
      controls.update()
    }

    if (grid) {
      const gridSize = clamp(Math.ceil(horizontalSpan * 1.6), 20, 240)
      const divisions = clamp(Math.ceil(gridSize / 3), 10, 80)
      grid.geometry.dispose()
      grid.geometry = new THREE.GridHelper(gridSize, divisions, 0x33515a, 0x1d333a).geometry
      grid.position.set(center.x, targetHeight, center.z)
      softenGrid(grid)
    }
  }, [centerHeight, normalizedLayers, totalPointCount, viewKey, webglSupported])

  useEffect(() => {
    if (!webglSupported) return
    const pathGroup = pathGroupRef.current
    if (!pathGroup) return

    pathGroup.children.forEach(disposeObject3D)
    pathGroup.clear()

    const addPath = (
      path: GlobalPath | ScanExecutionPath | null,
      options: {
        color: number
        targetColor: number
        radius: number
        zLift: number
        renderOrder: number
        markerLimit: number
      },
    ) => {
      if (!path || path.frame_id !== 'map' || path.points.length < 2) return

      const pathPoints = path.points.map((point) => {
        const converted = mapToThree(point.x, point.y, point.z)
        return new THREE.Vector3(converted.x, converted.y + options.zLift, converted.z)
      })
      const curve = new THREE.CatmullRomCurve3(pathPoints, false, 'centripetal')
      const tubularSegments = Math.max(8, Math.min(pathPoints.length * 2, 480))
      const geometry = new THREE.TubeGeometry(
        curve,
        tubularSegments,
        options.radius,
        8,
        false,
      )
      const material = new THREE.MeshBasicMaterial({
        color: options.color,
        transparent: true,
        opacity: 0.96,
        depthTest: true,
        depthWrite: false,
      })
      const pathMesh = new THREE.Mesh(geometry, material)
      pathMesh.renderOrder = options.renderOrder
      pathGroup.add(pathMesh)

      const markerStride = Math.max(1, Math.ceil(path.points.length / options.markerLimit))
      path.points.forEach((point, index) => {
        const isTarget = index === path.points.length - 1
        if (!isTarget && index % markerStride !== 0) return

        const converted = mapToThree(point.x, point.y, point.z)
        const marker = new THREE.Mesh(
          new THREE.SphereGeometry(
            isTarget ? GLOBAL_PATH_NODE_RADIUS * 1.5 : GLOBAL_PATH_NODE_RADIUS,
            16,
            10,
          ),
          new THREE.MeshBasicMaterial({
            color: isTarget ? options.targetColor : options.color,
            transparent: true,
            opacity: 0.98,
            depthTest: true,
            depthWrite: false,
          }),
        )
        marker.position.set(
          converted.x,
          converted.y + options.zLift,
          converted.z,
        )
        marker.renderOrder = options.renderOrder + 1
        pathGroup.add(marker)
      })
    }

    // Yellow: static-map Hybrid A* reference.
    addPath(globalPath, {
      color: 0xfacc15,
      targetColor: 0x22c55e,
      radius: GLOBAL_PATH_RADIUS,
      zLift: 0.03,
      renderOrder: 12,
      markerLimit: 80,
    })
    // Cyan: remaining SCAN body-centre B-spline, drawn above the reference.
    addPath(scanExecutionPath, {
      color: 0x22d3ee,
      targetColor: 0xe879f9,
      radius: GLOBAL_PATH_RADIUS * 1.2,
      zLift: 0.07,
      renderOrder: 16,
      markerLimit: 60,
    })

    return () => {
      pathGroup.children.forEach(disposeObject3D)
      pathGroup.clear()
    }
  }, [globalPath, scanExecutionPath, webglSupported])

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
          baseWidth: 1.8,
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
    const group = pendingGroupRef.current
    if (!group) return

    group.children.forEach(disposeObject3D)
    group.clear()

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
  }, [mode, pendingTarget, webglSupported])

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
    const camera = cameraRef.current
    const controls = controlsRef.current
    if (!robotGroup || !camera || !controls) return

    if (!robotPose) {
      robotGroup.visible = false
      return
    }

    const pos = mapToThree(robotPose.x, robotPose.y, robotPose.z)
    robotGroup.visible = true
    robotGroup.position.set(pos.x, pos.y, pos.z)
    robotGroup.rotation.y = robotPose.yaw

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

    if (mode === 'waypoint') {
      onAddWaypoint?.(target)
    } else {
      onSetPose?.(target)
    }
    pendingTargetRef.current = null
    setPendingTarget(null)
  }

  const scanPathAgeSeconds = scanExecutionPath?.received_at
    ? Math.max(0, pathClockMs / 1000 - scanExecutionPath.received_at)
    : null
  const scanPathFresh = scanPathAgeSeconds !== null && scanPathAgeSeconds <= 2.5

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

  return (
    <div className="pcd-viewer-shell">
      <div className="pcd-viewer-label">3D 点云</div>
      <div className="pcd-path-legend" aria-label="导航路径图例">
        <div>
          <span className="pcd-path-swatch is-global" />
          <span>全局路径</span>
          <strong>{globalPath?.points.length ?? 0} 点</strong>
        </div>
        <div>
          <span className="pcd-path-swatch is-scan" />
          <span>SCAN 机身轨迹</span>
          <strong>{scanExecutionPath?.points.length ?? 0} 点</strong>
          <em className={scanPathFresh ? 'is-fresh' : 'is-stale'}>
            {scanPathFresh
              ? '实时'
              : scanPathAgeSeconds === null
                ? '等待'
                : `${scanPathAgeSeconds.toFixed(1)}s 未更新`}
          </em>
        </div>
      </div>
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
      {totalPointCount === 0 ? <div className="pcd-viewer-empty">等待点云预览数据</div> : null}
    </div>
  )
}
