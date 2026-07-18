import * as THREE from 'three'
import { getPcdSceneTile } from '../../api/pcdMapApi'
import type {
  PcdBounds,
  PcdSceneLayerRole,
  PcdSceneTileManifest,
  PcdSceneTileNode,
  PcdSceneTilePayload,
  PointCloudQualityMode,
  WallColorMode,
} from '../../types/pcdMap'
import {
  createPointCloudMaterial,
  disposeObject3D,
  getLayerPreset,
  setPointCloudViewportHeight,
  setPointCloudWallColorMode,
} from './PointCloud3DViewerUtils'

type StaticLayerRole = Extract<PcdSceneLayerRole, 'ground' | 'wall' | 'footprint_fill'>

export type PointCloudTileStats = {
  phase: 'loading' | 'ready'
  visiblePoints: number
  loadedPoints: number
  totalPoints: number
  loadedBytes: number
  loadingCount: number
}

type TileDescriptor = {
  key: string
  nodeId: string
  role: StaticLayerRole
  bounds: PcdBounds
  payload: PcdSceneTilePayload
  priority: number
}

type LoadedTile = TileDescriptor & {
  cloud: THREE.Points
}

type PendingTile = {
  descriptor: TileDescriptor
  controller: AbortController
}

type ManagerOptions = {
  manifest: PcdSceneTileManifest
  camera: THREE.PerspectiveCamera
  renderer: THREE.WebGLRenderer
  group: THREE.Group
  wallColorMode: WallColorMode
  qualityMode: PointCloudQualityMode
  visibleRoles: Set<StaticLayerRole>
  onStats: (stats: PointCloudTileStats) => void
  onInvalidate: () => void
}

function threeBounds(bounds: PcdBounds) {
  return new THREE.Box3(
    new THREE.Vector3(bounds.min_x, bounds.min_z, -bounds.max_y),
    new THREE.Vector3(bounds.max_x, bounds.max_z, -bounds.min_y),
  )
}

function payloadForQuality(
  node: PcdSceneTileNode,
  qualityMode: PointCloudQualityMode,
): PcdSceneTilePayload {
  if (qualityMode === 'performance') return node.performance
  if (qualityMode === 'quality') return node.original
  return node.balanced
}

function descriptorForNode(
  node: PcdSceneTileNode,
  qualityMode: PointCloudQualityMode,
): TileDescriptor {
  return {
    key: `${node.id}:${qualityMode}`,
    nodeId: node.id,
    role: node.role,
    bounds: node.bounds,
    payload: payloadForQuality(node, qualityMode),
    priority: 0,
  }
}

/**
 * Loads every tile in the user-selected fixed density tier exactly once.
 *
 * Camera movement only reprioritizes tiles that have not started loading. A
 * loaded cloud is never hidden, replaced by another LOD, or evicted while the
 * scene remains mounted. Three.js can still frustum-cull whole final tiles at
 * draw time without changing the underlying point set.
 */
export class PointCloudTileManager {
  private readonly manifest: PcdSceneTileManifest
  private readonly camera: THREE.PerspectiveCamera
  private readonly renderer: THREE.WebGLRenderer
  private readonly group: THREE.Group
  private readonly onStats: ManagerOptions['onStats']
  private readonly onInvalidate: ManagerOptions['onInvalidate']
  private readonly descriptors = new Map<string, TileDescriptor>()
  private readonly loaded = new Map<string, LoadedTile>()
  private readonly pending = new Map<string, PendingTile>()
  private readonly retryAt = new Map<string, number>()
  private readonly retryAttempts = new Map<string, number>()
  private readonly retryTimers = new Map<string, number>()
  private totalPoints = 0
  private visibleRoles: Set<StaticLayerRole>
  private qualityMode: PointCloudQualityMode
  private wallColorMode: WallColorMode
  private moving = false
  private disposed = false
  private lastPriorityUpdateAt = 0

  constructor(options: ManagerOptions) {
    this.manifest = options.manifest
    this.camera = options.camera
    this.renderer = options.renderer
    this.group = options.group
    this.wallColorMode = options.wallColorMode
    this.qualityMode = options.qualityMode
    this.visibleRoles = new Set(options.visibleRoles)
    this.onStats = options.onStats
    this.onInvalidate = options.onInvalidate
    this.configureDescriptors()
    this.refreshPriorities(true)
  }

  setWallColorMode(mode: WallColorMode) {
    this.wallColorMode = mode
    this.loaded.forEach((tile) => {
      if (tile.role === 'wall') setPointCloudWallColorMode(tile.cloud.material, mode)
    })
    this.onInvalidate()
  }

  setQualityMode(mode: PointCloudQualityMode) {
    if (this.qualityMode === mode) return
    this.clearLoadedTier()
    this.qualityMode = mode
    this.configureDescriptors()
    this.lastPriorityUpdateAt = 0
    this.refreshPriorities(true)
  }

  setVisibleRoles(roles: Set<StaticLayerRole>) {
    this.visibleRoles = new Set(roles)
    this.loaded.forEach((tile) => {
      tile.cloud.visible = this.visibleRoles.has(tile.role)
    })
    this.refreshPriorities(true)
    this.onInvalidate()
  }

  setViewportHeight(height: number) {
    this.loaded.forEach((tile) => setPointCloudViewportHeight(tile.cloud.material, height))
  }

  update(moving: boolean, now = performance.now()) {
    if (this.moving !== moving) {
      this.moving = moving
      this.pumpQueue()
    }
    if (this.loaded.size >= this.descriptors.size) return
    const interval = moving ? 250 : 750
    if (now - this.lastPriorityUpdateAt < interval) return
    this.refreshPriorities(false)
  }

  private refreshPriorities(force: boolean) {
    if (this.disposed) return
    const now = performance.now()
    if (!force && now - this.lastPriorityUpdateAt < 250) return
    this.lastPriorityUpdateAt = now

    this.camera.updateMatrixWorld()
    const projectionView = new THREE.Matrix4().multiplyMatrices(
      this.camera.projectionMatrix,
      this.camera.matrixWorldInverse,
    )
    const frustum = new THREE.Frustum().setFromProjectionMatrix(projectionView)
    const viewportHeight = Math.max(1, this.renderer.domElement.clientHeight)
    const focalPixels = viewportHeight / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2))
    const cameraPosition = new THREE.Vector3()
    this.camera.getWorldPosition(cameraPosition)
    const cameraDirection = new THREE.Vector3()
    this.camera.getWorldDirection(cameraDirection)

    this.descriptors.forEach((descriptor) => {
      if (this.loaded.has(descriptor.key) || this.pending.has(descriptor.key)) return
      const box = threeBounds(descriptor.bounds)
      const center = box.getCenter(new THREE.Vector3())
      const sphere = box.getBoundingSphere(new THREE.Sphere())
      const radius = Math.max(0.05, sphere.radius)
      const distance = Math.max(0.1, cameraPosition.distanceTo(center) - radius)
      const projectedRadius = radius * focalPixels / distance
      const toCenter = center.clone().sub(cameraPosition).normalize()
      const centerBias = Math.max(0.05, cameraDirection.dot(toCenter) * 0.5 + 0.5)
      const inView = frustum.intersectsBox(box)
      descriptor.priority = (inView ? 1_000_000 : 0)
        + (this.visibleRoles.has(descriptor.role) ? 100_000 : 0)
        + projectedRadius * (0.65 + centerBias * 0.7)
        + 10_000 / Math.max(1, distance)
    })

    this.pumpQueue()
    this.emitStats()
  }

  private pumpQueue() {
    if (this.disposed) return
    const concurrency = this.qualityMode === 'quality'
      ? 1
      : this.moving ? 1 : 2
    const slots = Math.max(0, concurrency - this.pending.size)
    if (slots <= 0) return
    const now = performance.now()
    const queue = Array.from(this.descriptors.values())
      .filter((descriptor) => !this.loaded.has(descriptor.key) && !this.pending.has(descriptor.key))
      .filter((descriptor) => (this.retryAt.get(descriptor.key) ?? 0) <= now)
      .sort((a, b) => b.priority - a.priority)
      .slice(0, slots)
    queue.forEach((descriptor) => this.loadTile(descriptor))
  }

  private loadTile(descriptor: TileDescriptor) {
    const controller = new AbortController()
    this.pending.set(descriptor.key, { descriptor, controller })
    this.emitStats()
    void getPcdSceneTile(
      this.manifest.scene_id,
      descriptor.payload.file,
      this.manifest.cache_key,
      controller.signal,
    ).then((buffer) => {
      if (this.disposed || controller.signal.aborted) return
      const expectedBytes = descriptor.payload.point_count * (descriptor.payload.has_intensity ? 13 : 12)
      if (buffer.byteLength !== expectedBytes || descriptor.payload.byte_length !== expectedBytes) {
        throw new Error(`点云瓦片长度不匹配: ${descriptor.payload.file}`)
      }
      const cloud = this.createCloud(descriptor, buffer)
      cloud.visible = this.visibleRoles.has(descriptor.role)
      this.group.add(cloud)
      this.loaded.set(descriptor.key, { ...descriptor, cloud })
      this.retryAt.delete(descriptor.key)
      this.retryAttempts.delete(descriptor.key)
      const retryTimer = this.retryTimers.get(descriptor.key)
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
      this.retryTimers.delete(descriptor.key)
      this.onInvalidate()
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return
      console.warn('加载点云瓦片失败，将自动重试', descriptor.payload.file, error)
      const attempts = (this.retryAttempts.get(descriptor.key) ?? 0) + 1
      const delay = Math.min(30_000, 1_000 * 2 ** Math.min(attempts - 1, 5))
      this.retryAttempts.set(descriptor.key, attempts)
      this.retryAt.set(descriptor.key, performance.now() + delay)
      const retryTimer = window.setTimeout(() => {
        this.retryTimers.delete(descriptor.key)
        this.retryAt.delete(descriptor.key)
        this.pumpQueue()
        this.emitStats()
      }, delay)
      this.retryTimers.set(descriptor.key, retryTimer)
    }).finally(() => {
      this.pending.delete(descriptor.key)
      if (!this.disposed) {
        this.pumpQueue()
        this.emitStats()
      }
    })
  }

  private createCloud(descriptor: TileDescriptor, buffer: ArrayBuffer) {
    const pointCount = descriptor.payload.point_count
    const positions = new Float32Array(buffer, 0, pointCount * 3)
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    if (descriptor.payload.has_intensity) {
      geometry.setAttribute(
        'intensity',
        new THREE.Uint8BufferAttribute(new Uint8Array(buffer, pointCount * 12, pointCount), 1, true),
      )
    }
    const box = threeBounds(descriptor.bounds)
    geometry.boundingBox = box
    geometry.boundingSphere = box.getBoundingSphere(new THREE.Sphere())

    const preset = getLayerPreset(descriptor.role)
    const wallBounds = this.manifest.layer_bounds.wall
    const material = createPointCloudMaterial(preset, 1, {
      minHeight: wallBounds?.min_z ?? descriptor.bounds.min_z,
      maxHeight: wallBounds?.max_z ?? descriptor.bounds.max_z,
      wallColorMode: this.wallColorMode,
      viewportHeight: this.renderer.domElement.height,
      hasIntensity: descriptor.payload.has_intensity,
    })
    const cloud = new THREE.Points(geometry, material)
    cloud.renderOrder = preset.renderOrder
    cloud.userData.role = descriptor.role
    cloud.userData.tileKey = descriptor.key
    return cloud
  }

  private emitStats() {
    let visiblePoints = 0
    let loadedPoints = 0
    let loadedBytes = 0
    this.loaded.forEach((tile) => {
      loadedPoints += tile.payload.point_count
      loadedBytes += tile.payload.byte_length
      if (tile.cloud.visible) visiblePoints += tile.payload.point_count
    })
    this.onStats({
      phase: this.loaded.size >= this.descriptors.size ? 'ready' : 'loading',
      visiblePoints,
      loadedPoints,
      totalPoints: this.totalPoints,
      loadedBytes,
      loadingCount: this.pending.size,
    })
  }

  private configureDescriptors() {
    this.manifest.nodes.forEach((node) => {
      const descriptor = descriptorForNode(node, this.qualityMode)
      this.descriptors.set(descriptor.key, descriptor)
    })
    this.totalPoints = Array.from(this.descriptors.values()).reduce(
      (sum, descriptor) => sum + descriptor.payload.point_count,
      0,
    )
  }

  private clearLoadedTier() {
    this.pending.forEach((pending) => pending.controller.abort())
    this.pending.clear()
    this.retryTimers.forEach((timer) => window.clearTimeout(timer))
    this.retryTimers.clear()
    this.retryAt.clear()
    this.retryAttempts.clear()
    this.loaded.forEach((tile) => {
      this.group.remove(tile.cloud)
      disposeObject3D(tile.cloud)
    })
    this.loaded.clear()
    this.descriptors.clear()
    this.onInvalidate()
  }

  dispose() {
    this.disposed = true
    this.clearLoadedTier()
  }
}
