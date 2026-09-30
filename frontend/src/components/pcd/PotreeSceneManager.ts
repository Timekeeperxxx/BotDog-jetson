import { heightIntersects, NO_HEIGHT_CLIP, setMaterialHeightClip, type HeightClip } from './PointCloudHeightClip'
import { setPointCloudPointSize, setPointCloudIntensityPreference } from './PointCloud3DViewerUtils'
import * as THREE from 'three'
import { Potree, ClipMode, createClipBox, type PointCloudOctree } from 'potree-core'
import type { OctreeGeometry } from 'potree-core/dist/loading2/OctreeGeometry'
import type { OctreeGeometryNode } from 'potree-core/dist/loading2/OctreeGeometryNode'
import { fetchWithAuth } from '../../api/apiFetch'
import type { PcdSceneTileManifest, WallColorMode } from '../../types/pcdMap'
import type { PointCloudTileStats } from './PointCloudTileManager'
import { createPointCloudMaterial, getLayerPreset, setPointCloudViewport, setPointCloudWallColorMode } from './PointCloud3DViewerUtils'
import { PotreeMotionTracker, predictCameraPosition, type CloudMotion } from './PotreeMotion'
import { intensityRank } from './PointCloudIntensity'
import { PotreeOcclusion } from './PotreeOcclusion'
import { PotreePerformance, PotreeGpuTimer } from './PotreePerformance'
import { PotreeLoadRamp, refineWithinBudget } from './PotreeLoading'

type Role = 'ground' | 'wall' | 'footprint_fill'
type Entry = { role: Role; cloud: PointCloudOctree; geometry: OctreeGeometry; material: THREE.ShaderMaterial }
type Candidate = { entry: Entry; node: OctreeGeometryNode; key: string; box: THREE.Box3 }
type Options = {
  manifest: PcdSceneTileManifest; camera: THREE.PerspectiveCamera; renderer: THREE.WebGLRenderer
  group: THREE.Group; wallColorMode: WallColorMode; visibleRoles: Set<Role>
  onStats: (stats: PointCloudTileStats) => void; onInvalidate: () => void
}

/** Potree owns the octree, worker decoding and visibility traversal. This adapter
 * keeps BotDog's materials/overlays and schedules original data without a
 * point-count, RAM or VRAM cap. Moving (including robot following) never switches to a lower quality tier. */
export class PotreeSceneManager {
  private loadRamp = new PotreeLoadRamp()
  private performance = new PotreePerformance()
  private gpu: PotreeGpuTimer
  private renderStart = 0
  private renderCost = 0
  private updateCost = 0
  private potree = new Potree()
  private entries: Entry[] = []
  private candidates = new Map<string, Candidate>()
  private controller = new AbortController()
  private workers = new Set<Worker>()
  private occlusion: PotreeOcclusion
  private motion = new PotreeMotionTracker()
  private mode: CloudMotion = 'stationary'
  private visibleRoles: Set<Role>
  private disposed = false
  private loadingMetadata = true
  private lastUpdate = 0
  private lastStats = 0
  private lastFrame = 0
  private frameMs = 16
  private loadedBytes = 0
  private hierarchyFiles = new Map<string, Promise<ArrayBuffer>>()
  private error: string | undefined
  private wallColorMode: WallColorMode
  private retryAt = new Map<string, number>()
  private failedNodes = new Set<string>()
  private normalized = new WeakSet<THREE.BufferGeometry>()
  private occluders: THREE.Points[] = []

  private options: Options
  constructor(options: Options) {
    this.options = options
    this.gpu = new PotreeGpuTimer(options.renderer.getContext() as WebGL2RenderingContext)
    this.visibleRoles = new Set(options.visibleRoles)
    this.wallColorMode = options.wallColorMode
    this.potree.pointBudget = Infinity
    this.potree.maxNumNodesLoading = Infinity
    this.occlusion = new PotreeOcclusion(options.renderer)
    void this.load()
  }

  private async load() {
    const { manifest, renderer, group } = this.options
    await Promise.all(manifest.potree!.layers.map(async (layer) => {
      try {
        const cloud = await this.potree.loadPointCloud(layer.url, {
          getUrl: async (url: string) => url,
          fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
            const path = String(input)
            const range = new Headers(init?.headers).get('Range')
            if (range && path.endsWith('/hierarchy.bin')) {
              const match = /^bytes=(\d+)-(\d+)$/.exec(range)
              if (!match) throw new Error('无效的点云层级范围')
              let download = this.hierarchyFiles.get(path)
              if (!download) {
                download = fetchWithAuth(path, {
                  signal: AbortSignal.any([this.controller.signal, AbortSignal.timeout(30000)]),
                }).then(async response => {
                  if (!response.ok) throw new Error(`点云层级请求失败：HTTP ${response.status}`)
                  const data = await response.arrayBuffer()
                  this.loadedBytes += data.byteLength
                  return data
                }).catch(error => { this.hierarchyFiles.delete(path); throw error })
                this.hierarchyFiles.set(path, download)
              }
              const data = await download
              const begin = Number(match[1]), end = Number(match[2])
              if (end >= data.byteLength || begin > end) throw new Error('点云层级范围超出文件')
              return new Response(data.slice(begin, end + 1), { status: 206, headers: {
                'Content-Range': `bytes ${begin}-${end}/${data.byteLength}`,
                'Content-Length': String(end - begin + 1),
              } })
            }
            const response = await fetchWithAuth(path, { ...init,
              signal: AbortSignal.any([this.controller.signal, AbortSignal.timeout(30000)]) })
            if (!response.ok) throw new Error(`点云请求失败：HTTP ${response.status}`)
            if (range && response.status !== 206) {
              await response.body?.cancel()
              throw new Error('点云服务未返回分段数据（206），已停止整文件下载')
            }
            this.loadedBytes += Number(response.headers.get('content-length') || 0)
            return response
          },
        })
        if (this.disposed) { cloud.dispose(); return }
        cloud.minNodePixelSize = 0
        cloud.maxLevel = Infinity
        cloud.visible = this.visibleRoles.has(layer.role)
        const geometry = cloud.pcoGeometry as OctreeGeometry
        const bounds = manifest.layer_bounds.wall ?? manifest.bounds
        const material = createPointCloudMaterial(getLayerPreset(layer.role), renderer.getPixelRatio(), {
          minHeight: bounds.min_z, maxHeight: bounds.max_z, wallColorMode: this.wallColorMode,
          viewportHeight: renderer.domElement.height, hasIntensity: true, intensityPreference: this.intensityPreference, pointSizeScale: this.pointSizeScale,
        })
        const entry: Entry = { role: layer.role, cloud, geometry, material }
        this.entries.push(entry)
        this.applyHeightClip(entry)
        group.add(cloud)
        group.updateMatrixWorld(true)
        const pool = geometry.loader.workerPool
        const getWorker = pool.getWorker.bind(pool)
        pool.getWorker = (type) => {
          if (this.disposed) throw new DOMException('Scene disposed', 'AbortError')
          const worker = getWorker(type)
          this.workers.add(worker)
          return worker
        }
        const loadNode = geometry.loader.load.bind(geometry.loader)
        geometry.loader.load = async (node) => {
          if (this.disposed || node.loaded || node.loading) return
          const key = `${layer.role}:${node.name}`
          const box = node.boundingBox.clone().translate(cloud.position)
          if (heightIntersects(box.min.y, box.max.y, this.heightClip)) this.candidates.set(key, { entry, node, key, box })
        }
        // Keep the real loader separately; it marks loading synchronously and
        // worker completion decrements geometry.numNodesLoading asynchronously.
        this.loaders.set(entry, loadNode)
        this.options.onInvalidate()
      } catch (error) {
        if (!this.disposed) this.error = error instanceof Error ? error.message : '点云初始化失败'
      }
    }))
    this.loadingMetadata = false
    this.options.onInvalidate()
    this.emitStats(performance.now(), true)
  }

  private loaders = new Map<Entry, (node: OctreeGeometryNode) => Promise<void>>()

  update(interacting: boolean, now = performance.now(), following = false) {
    if (this.disposed) return
    const started = performance.now()
    const { camera, renderer } = this.options
    const active = !document.hidden && renderer.domElement.height > 0
    if (this.lastFrame) this.performance.sample(now - this.lastFrame,
      Math.max(this.renderCost, this.gpu.milliseconds) + this.updateCost, active, this.mode === 'stationary')
    if (this.lastFrame) this.frameMs = this.frameMs * 0.9 + Math.min(now - this.lastFrame, 100) * 0.1
    this.lastFrame = now
    if (!active) return
    const mode = this.motion.update(camera, interacting, following, now)
    const changedMode = mode !== this.mode
    this.mode = mode
    this.occlusion.update(camera)
    // Rendering remains per animation frame; traversing the hierarchy is less
    // frequent while moving. A stop immediately starts refinement again.
    if (!changedMode && now - this.lastUpdate < (mode === 'stationary' ? 0 : 40)) return
    this.lastUpdate = now
    this.candidates.clear()
    const concurrency = this.loadRamp.next(mode, now, this.frameMs,
      Math.max(this.renderCost, this.gpu.milliseconds) + this.updateCost)
    this.entries.forEach(({ geometry }) => { geometry.maxNumNodesLoading = concurrency })
    const clouds = this.entries.filter((e) => this.visibleRoles.has(e.role)).map((e) => e.cloud)
    clouds.forEach((cloud) => { cloud.minNodePixelSize = this.performance.radius * renderer.getPixelRatio() })
    // Reserve time for rendering (including last frame's uploads). Repeated
    // traversal admits more ready nodes only when the previous frame had headroom.
    const uploadBudget = mode === 'stationary'
      ? Math.max(0, Math.min(4, 12 - Math.max(this.renderCost, this.gpu.milliseconds) - this.updateCost)) : 0
    const result = refineWithinBudget(() => this.potree.updatePointClouds(clouds, camera, renderer), uploadBudget)
    this.occluders = []
    for (const entry of this.entries) {
      if (!entry.cloud.visible) continue
      for (const node of entry.cloud.visibleNodes) {
        const key = `${entry.role}:${node.name}`
        this.retryAt.delete(key)
        if (this.failedNodes.delete(key) && !this.failedNodes.size) this.error = undefined
        const points = node.sceneNode
        points.renderOrder = getLayerPreset(entry.role).renderOrder
        points.material = entry.material
        points.onBeforeRender = () => undefined
        points.userData.role = entry.role
        const geometry = points.geometry
        if (!this.normalized.has(geometry)) {
          const intensity = geometry.getAttribute('intensity')
          const range = this.options.manifest.stats[entry.role]?.intensity_percentile_2_98 ?? [0, 1]
          const quantiles = this.options.manifest.stats[entry.role]?.intensity_quantiles
          if (intensity) {
            for (let i = 0; i < intensity.count; i++) {
              intensity.setX(i, quantiles ? intensityRank(intensity.getX(i), quantiles)
                : THREE.MathUtils.clamp((intensity.getX(i) - range[0]) / Math.max(1e-6, range[1] - range[0]), 0, 1))
            }
            intensity.needsUpdate = true
          }
          this.normalized.add(geometry)
        }
        if (entry.role !== 'footprint_fill') this.occluders.push(points)
      }
    }
    if (mode === 'following') this.prefetch(camera)
    this.pump(concurrency, now)
    if (result.exceededMaxLoadsToGPU || result.nodeLoadPromises.length) this.options.onInvalidate()
    this.emitStats(now)
    this.updateCost = performance.now() - started
  }

  private prefetch(camera: THREE.PerspectiveCamera) {
    const predicted = camera.clone()
    predicted.position.copy(predictCameraPosition(camera.position, this.motion.velocity))
    predicted.updateMatrixWorld()
    const frustum = new THREE.Frustum().setFromProjectionMatrix(new THREE.Matrix4()
      .multiplyMatrices(predicted.projectionMatrix, predicted.matrixWorldInverse))
    // Only inspect the frontier of already-visible hierarchy; never enumerate
    // an entire scene merely to prefetch around the robot.
    for (const entry of this.entries) {
      if (!entry.cloud.visible) continue
      for (const visible of entry.cloud.visibleNodes) {
        for (const child of visible.children) {
          if (!child || child.loaded) continue
          const node = child as OctreeGeometryNode
          const box = node.boundingBox.clone().translate(entry.cloud.position)
          const key = `${entry.role}:${node.name}`
          const sphere = box.getBoundingSphere(new THREE.Sphere())
          const distance = predicted.position.distanceTo(sphere.center)
          const radius = sphere.radius * this.options.renderer.domElement.height
            / (2 * Math.tan(THREE.MathUtils.degToRad(predicted.fov) / 2) * Math.max(distance, 1e-6))
          const detailed = distance <= sphere.radius || radius >= this.performance.radius * this.options.renderer.getPixelRatio()
          if (heightIntersects(box.min.y, box.max.y, this.heightClip) && detailed && frustum.intersectsBox(box) && !this.candidates.has(key)) {
            if (heightIntersects(box.min.y, box.max.y, this.heightClip)) this.candidates.set(key, { entry, node, key, box })
          }
        }
      }
    }
  }

  private pump(concurrency: number, now: number) {
    let active = this.entries.reduce((n, e) => n + e.geometry.numNodesLoading, 0)
    for (const candidate of this.candidates.values()) {
      const { node, entry, key } = candidate
      if (active >= concurrency) break
      if (!heightIntersects(candidate.box.min.y, candidate.box.max.y, this.heightClip) || node.loaded || node.loading || this.occlusion.isHidden(key) || (this.retryAt.get(key) ?? 0) > now) continue
      active++
      this.retryAt.set(key, now + 2000)
      void this.loaders.get(entry)!(node).then(() => {
        if (!node.loading && !node.loaded && !this.disposed) {
          this.failedNodes.add(key)
          this.error = '部分点云加载失败，正在重试'
        }
        this.options.onInvalidate()
      })
    }
  }

  beforeRender() {
    this.renderStart = performance.now()
    this.gpu.begin()
  }

  afterRender(now: number) {
    this.gpu.end()
    this.renderCost = performance.now() - this.renderStart
    if (this.mode !== 'stationary' || this.disposed) return
    const candidates = [...this.candidates.values()].filter((c) => !c.node.loaded && !c.node.loading)
    this.occlusion.probe(this.options.camera, candidates, this.occluders, now)
  }

  private emitStats(now: number, force = false) {
    if (!force && now - this.lastStats < 300) return
    this.lastStats = now
    const loadingCount = this.entries.reduce((n, e) => n + e.geometry.numNodesLoading, 0)
    const visiblePoints = this.entries.reduce((n, e) => n + (e.cloud.visible
      ? e.cloud.visibleNodes.reduce((sum, node) => sum + node.numPoints, 0) : 0), 0)
    const pending = [...this.candidates.values()].some((c) => !c.node.loaded && !this.occlusion.isHidden(c.key))
    this.options.onStats({
      phase: this.loadingMetadata || loadingCount || pending ? 'loading' : 'ready',
      loadedPoints: this.potree.lru.numPoints, visiblePoints,
      totalPoints: this.options.manifest.potree!.layers.reduce((n, l) => n + l.point_count, 0),
      loadedBytes: this.loadedBytes, loadingCount, motion: this.mode, error: this.error,
    })
  }

  private heightClip: HeightClip = NO_HEIGHT_CLIP
  private applyHeightClip(entry: Entry) {
    setMaterialHeightClip(entry.material, this.heightClip)
    if (this.heightClip.min === null && this.heightClip.max === null) {
      entry.cloud.material?.setClipBoxes([])
      return
    }
    const b = this.options.manifest.bounds
    const low = this.heightClip.min ?? b.min_z - 1
    const high = this.heightClip.max ?? b.max_z + 1
    const box = createClipBox(new THREE.Vector3(b.max_x - b.min_x + 2, Math.max(1e-6, high - low), b.max_y - b.min_y + 2),
      new THREE.Vector3((b.min_x + b.max_x) / 2, (low + high) / 2, -(b.min_y + b.max_y) / 2))
    entry.cloud.material.setClipBoxes([box])
    entry.cloud.material.clipMode = ClipMode.CLIP_OUTSIDE
  }
  setHeightClip(clip: HeightClip) {
    this.heightClip = clip
    this.entries.forEach(entry => this.applyHeightClip(entry))
    this.candidates.clear()
    this.occlusion.invalidate()
    this.options.onInvalidate()
  }

  private pointSizeScale = 1
  setPointSize(value: number) {
    this.pointSizeScale = value
    this.entries.forEach(e => setPointCloudPointSize(e.material, value))
    this.occlusion.invalidate()
    this.options.onInvalidate()
  }

  private intensityPreference = 0

  setIntensityPreference(value: number) {
    this.intensityPreference = value
    this.entries.forEach(e => setPointCloudIntensityPreference(e.material, value))
    this.options.onInvalidate()
  }

  setWallColorMode(mode: WallColorMode) {
    this.wallColorMode = mode
    this.entries.filter((e) => e.role === 'wall').forEach((e) => setPointCloudWallColorMode(e.material, mode))
    this.options.onInvalidate()
  }

  setVisibleRoles(roles: Set<Role>) {
    this.visibleRoles = new Set(roles)
    this.entries.forEach((e) => { e.cloud.visible = roles.has(e.role) })
    this.occlusion.invalidate()
    this.options.onInvalidate()
  }

  setQualityMode() { /* Original only. */ }
  pickGround(pointerX: number, pointerY: number, width: number, height: number, threshold: number) {
    const camera = this.options.camera
    const ray = new THREE.Raycaster()
    ray.setFromCamera(new THREE.Vector2(pointerX / width * 2 - 1, 1 - pointerY / height * 2), camera)
    let best: THREE.Vector3 | null = null
    let bestDistance = threshold * threshold
    let bestDepth = Infinity
    const world = new THREE.Vector3(), screen = new THREE.Vector3()
    for (const entry of this.entries) {
      if (entry.role !== 'ground' || !entry.cloud.visible) continue
      for (const node of entry.cloud.visibleNodes) {
        const box = node.boundingBox.clone().translate(entry.cloud.position)
        const sphere = box.getBoundingSphere(new THREE.Sphere())
        const radius = threshold * 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))
          * (camera.position.distanceTo(sphere.center) + sphere.radius) / height
        if (!ray.ray.intersectsBox(box.expandByScalar(radius))) continue
        const object = node.sceneNode
        const positions = object.geometry.getAttribute('position')
        // Potree supplies absolute node matrices. Calling updateMatrixWorld on
        // nested scene nodes here would add their parent offsets twice.
        for (let i = 0; i < positions.count; i++) {
          world.fromBufferAttribute(positions, i).applyMatrix4(object.matrixWorld)
          if (!heightIntersects(world.y, world.y, this.heightClip)) continue
          screen.copy(world).project(camera)
          if (screen.z < -1 || screen.z > 1) continue
          const dx = (screen.x * 0.5 + 0.5) * width - pointerX
          const dy = (0.5 - screen.y * 0.5) * height - pointerY
          const distance = dx * dx + dy * dy
          if (distance < bestDistance || (distance === bestDistance && screen.z < bestDepth)) {
            bestDistance = distance
            bestDepth = screen.z
            best = world.clone()
          }
        }
      }
    }
    return best
  }

  setViewport(height: number, ratio: number) {
    this.entries.forEach((e) => {
      setPointCloudViewport(e.material, height, ratio)
      e.cloud.minNodePixelSize = 0
    })
    this.occlusion.invalidate()
  }

  dispose() {
    this.disposed = true
    this.controller.abort()
    this.workers.forEach((w) => w.terminate())
    for (const entry of this.entries) {
      this.options.group.remove(entry.cloud)
      entry.geometry.root.traverse((node) => node.geometry?.dispose())
      entry.cloud.dispose()
      entry.material.dispose()
    }
    this.entries = []
    this.workers.clear()
    this.candidates.clear()
    this.hierarchyFiles.clear()
    this.occlusion.dispose()
    this.gpu.dispose()
  }
}
