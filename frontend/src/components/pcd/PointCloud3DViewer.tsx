import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { NavWaypoint, PcdSceneLayerRole } from '../../types/pcdMap'
import type { GlobalPath, RobotPose } from '../../types/navState'
import { mapToThree } from '../../utils/pointCloudTransform'
import { detectWebGLSupport } from './webglSupport'

type PointCloudLayer = {
  role: PcdSceneLayerRole
  points: [number, number, number][]
}

const WAYPOINT_COLOR = 0xfbbf24
const ROBOT_BODY_COLOR = 0xf97316
const ROBOT_ARROW_COLOR = 0xf97316
const WAYPOINT_ARROW_LENGTH = 0.62
const WAYPOINT_ARROW_HEAD_LENGTH = 0.22
const WAYPOINT_ARROW_HEAD_WIDTH = 0.12
const ROBOT_ARROW_LENGTH = 0.62
const ROBOT_ARROW_HEAD_LENGTH = 0.22
const ROBOT_ARROW_HEAD_WIDTH = 0.12

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function disposeMaterial(material: THREE.Material | THREE.Material[]) {
  if (Array.isArray(material)) {
    material.forEach((item) => item.dispose())
  } else {
    material.dispose()
  }
}

function disposeObject3D(object: THREE.Object3D) {
  if (object instanceof THREE.Mesh) {
    object.geometry.dispose()
    disposeMaterial(object.material)
    return
  }

  if (object instanceof THREE.Line) {
    object.geometry.dispose()
    disposeMaterial(object.material)
    return
  }

  if (object instanceof THREE.Points) {
    object.geometry.dispose()
    disposeMaterial(object.material)
    return
  }

  if (object instanceof THREE.Sprite) {
    const material = object.material
    material.map?.dispose()
    material.dispose()
    return
  }

  if (object instanceof THREE.ArrowHelper) {
    object.line.geometry.dispose()
    object.cone.geometry.dispose()
    disposeMaterial(object.line.material)
    disposeMaterial(object.cone.material)
    return
  }
}

function createMapYawDirection(yaw: number) {
  return new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw)).normalize()
}

function createWaypointLabelSprite(text: string) {
  const canvas = document.createElement('canvas')
  const width = 256
  const height = 64
  canvas.width = width
  canvas.height = height

  const ctx = canvas.getContext('2d')
  if (!ctx) return null

  ctx.clearRect(0, 0, width, height)
  ctx.fillStyle = 'rgba(7, 14, 20, 0.56)'
  ctx.strokeStyle = 'rgba(251, 191, 36, 0.28)'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.roundRect(2, 2, width - 4, height - 4, 12)
  ctx.fill()
  ctx.stroke()

  ctx.fillStyle = 'rgba(248, 250, 252, 0.94)'
  ctx.font = 'bold 26px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, width / 2, height / 2)

  const texture = new THREE.CanvasTexture(canvas)
  texture.minFilter = THREE.LinearFilter
  texture.magFilter = THREE.LinearFilter

  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthTest: false,
  })
  const sprite = new THREE.Sprite(material)
  sprite.scale.set(1.8, 0.45, 1)
  sprite.renderOrder = 50
  return sprite
}

function getLayerColor(role: PcdSceneLayerRole) {
  return role === 'ground' ? 0x38bdf8 : 0x166534
}

type Props = {
  layers?: PointCloudLayer[]
  points?: [number, number, number][]
  waypoints: NavWaypoint[]
  robotPose: RobotPose | null
  globalPath: GlobalPath | null
  followRobot?: boolean
  centerHeight?: number | null
}

export function PointCloud3DViewer({
  layers,
  points,
  waypoints,
  robotPose,
  globalPath,
  followRobot = false,
  centerHeight = null,
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
  const robotGroupRef = useRef<THREE.Group | null>(null)

  const normalizedLayers: PointCloudLayer[] =
    layers?.length
      ? layers
      : points && points.length > 0
        ? [{ role: 'ground', points }]
        : []
  const totalPointCount = normalizedLayers.reduce((sum, layer) => sum + layer.points.length, 0)

  useEffect(() => {
    if (!webglSupported) return
    const host = hostRef.current
    if (!host) return

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x071013)
    sceneRef.current = scene

    const camera = new THREE.PerspectiveCamera(55, 1, 0.01, 10000)
    camera.position.set(8, 8, 8)
    camera.lookAt(0, 0, 0)
    cameraRef.current = camera

    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
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

    const robotGroup = new THREE.Group()
    robotGroup.visible = false
    const body = new THREE.Mesh(
      new THREE.CylinderGeometry(0.18, 0.18, 0.18, 18),
      new THREE.MeshBasicMaterial({ color: ROBOT_BODY_COLOR }),
    )
    body.position.y = 0.09
    body.renderOrder = 30
    robotGroup.add(body)

    const direction = new THREE.ArrowHelper(
      new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(0, 0.18, 0),
      ROBOT_ARROW_LENGTH,
      ROBOT_ARROW_COLOR,
      ROBOT_ARROW_HEAD_LENGTH,
      ROBOT_ARROW_HEAD_WIDTH,
    )
    direction.renderOrder = 31
    robotGroup.add(direction)
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
      controls.target.set(0, 0, 0)
      camera.position.set(18, 12, 18)
      camera.near = 0.01
      camera.far = 10000
      camera.updateProjectionMatrix()
      controls.update()
      return
    }

    const unionBox = new THREE.Box3()
    let hasPoints = false

    normalizedLayers.forEach((layer) => {
      if (layer.points.length === 0) return

      const positions = new Float32Array(layer.points.length * 3)
      const layerBox = new THREE.Box3()
      layer.points.forEach(([x, y, z], index) => {
        const converted = mapToThree(x, y, z)
        positions[index * 3] = converted.x
        positions[index * 3 + 1] = converted.y
        positions[index * 3 + 2] = converted.z
        layerBox.expandByPoint(new THREE.Vector3(converted.x, converted.y, converted.z))
      })

      const geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
      geometry.computeBoundingBox()
      geometry.computeBoundingSphere()

      const material = new THREE.PointsMaterial({
        color: getLayerColor(layer.role),
        size: 0.07,
        sizeAttenuation: true,
      })

      const cloud = new THREE.Points(geometry, material)
      cloud.renderOrder = layer.role === 'ground' ? 1 : 2
      cloudGroup.add(cloud)

      if (!hasPoints) {
        unionBox.copy(layerBox)
        hasPoints = true
      } else {
        unionBox.union(layerBox)
      }
    })

    if (!hasPoints) {
      controls.target.set(0, 0, 0)
      camera.position.set(18, 12, 18)
      camera.near = 0.01
      camera.far = 10000
      camera.updateProjectionMatrix()
      controls.update()
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

    controls.target.copy(center)
    controls.target.y = targetHeight
    camera.position.copy(controls.target.clone().add(direction.multiplyScalar(distance)))
    camera.near = Math.max(0.01, distance / 500)
    camera.far = Math.max(1000, distance * 30)
    camera.updateProjectionMatrix()
    controls.minDistance = Math.max(0.5, distance * 0.2)
    controls.maxDistance = Math.max(10, distance * 8)
    controls.update()

    if (grid) {
      const gridSize = clamp(Math.ceil(horizontalSpan * 1.6), 20, 240)
      const divisions = clamp(Math.ceil(gridSize / 3), 10, 80)
      grid.geometry.dispose()
      grid.geometry = new THREE.GridHelper(gridSize, divisions, 0x33515a, 0x1d333a).geometry
      grid.position.set(center.x, targetHeight, center.z)
    }
  }, [centerHeight, normalizedLayers, webglSupported])

  useEffect(() => {
    if (!webglSupported) return
    const scene = sceneRef.current
    const pathGroup = pathGroupRef.current
    if (!scene || !pathGroup) return

    pathGroup.children.forEach(disposeObject3D)
    pathGroup.clear()

    if (!globalPath || globalPath.frame_id !== 'map' || globalPath.points.length < 2) {
      return
    }

    const positions = new Float32Array(globalPath.points.length * 3)
    const zLift = 0.03
    globalPath.points.forEach((point, index) => {
      const converted = mapToThree(point.x, point.y, point.z)
      positions[index * 3] = converted.x
      positions[index * 3 + 1] = converted.y + zLift
      positions[index * 3 + 2] = converted.z
    })

    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))

    const material = new THREE.LineBasicMaterial({
      color: 0xfacc15,
      transparent: true,
      opacity: 0.95,
      depthTest: false,
    })

    const pathLine = new THREE.Line(geometry, material)
    pathLine.renderOrder = 20
    pathGroup.add(pathLine)

    return () => {
      pathGroup.children.forEach(disposeObject3D)
      pathGroup.clear()
    }
  }, [globalPath, webglSupported])

  useEffect(() => {
    if (!webglSupported) return
    const group = waypointGroupRef.current
    if (!group) return

    group.children.forEach(disposeObject3D)
    group.clear()

    waypoints.forEach((waypoint) => {
      const pos = mapToThree(waypoint.x, waypoint.y, waypoint.z)
      const sphere = new THREE.Mesh(
        new THREE.SphereGeometry(0.16, 16, 12),
        new THREE.MeshBasicMaterial({ color: WAYPOINT_COLOR }),
      )
      sphere.position.set(pos.x, pos.y + 0.12, pos.z)
      sphere.renderOrder = 40
      group.add(sphere)

      const arrow = new THREE.ArrowHelper(
        createMapYawDirection(waypoint.yaw),
        new THREE.Vector3(pos.x, pos.y + 0.18, pos.z),
        WAYPOINT_ARROW_LENGTH,
        WAYPOINT_COLOR,
        WAYPOINT_ARROW_HEAD_LENGTH,
        WAYPOINT_ARROW_HEAD_WIDTH,
      )
      arrow.renderOrder = 41
      group.add(arrow)

      const label = createWaypointLabelSprite(waypoint.name)
      if (label) {
        label.position.set(pos.x, pos.y + 0.58, pos.z)
        label.renderOrder = 50
        group.add(label)
      }
    })
  }, [waypoints, webglSupported])

  useEffect(() => {
    if (!webglSupported) return
    const controls = controlsRef.current
    if (!controls) return

    controls.enablePan = !followRobot
    controls.update()

    return () => {
      controls.enablePan = true
    }
  }, [followRobot, webglSupported])

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
      <div className="pcd-three-host" ref={hostRef} />
      {totalPointCount === 0 ? <div className="pcd-viewer-empty">等待点云预览数据</div> : null}
    </div>
  )
}
