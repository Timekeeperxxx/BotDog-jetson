import * as THREE from 'three'

type Result = { query: WebGLQuery; key: string; generation: number }

/** Conservative box queries against opaque point fragments only. No CPU readback
 * waits, no filled-in walls, no assumption that a sparse point cloud is solid. */
export class PotreeOcclusion {
  private gl: WebGL2RenderingContext
  private target = new THREE.WebGLRenderTarget(1, 1)
  private boxGeometry = new THREE.BoxGeometry(1, 1, 1)
  private boxMaterial = new THREE.MeshBasicMaterial({ colorWrite: false, depthWrite: false,
    depthTest: true, side: THREE.DoubleSide })
  private pending: Result[] = []
  private hidden = new Set<string>()
  private tested = new Set<string>()
  private generation = 0
  private cameraMatrix = new THREE.Matrix4()
  private projection = new THREE.Matrix4()
  private lastProbe = -Infinity

  private renderer: THREE.WebGLRenderer
  constructor(renderer: THREE.WebGLRenderer) {
    this.renderer = renderer
    this.gl = renderer.getContext() as WebGL2RenderingContext
  }

  invalidate() {
    this.generation++
    this.hidden.clear()
    this.tested.clear()
  }

  update(camera: THREE.Camera) {
    camera.updateMatrixWorld()
    if (!this.cameraMatrix.equals(camera.matrixWorld) || !this.projection.equals(camera.projectionMatrix)) {
      this.cameraMatrix.copy(camera.matrixWorld)
      this.projection.copy(camera.projectionMatrix)
      this.invalidate()
    }
    this.pending = this.pending.filter((result) => {
      if (!this.gl.getQueryParameter(result.query, this.gl.QUERY_RESULT_AVAILABLE)) return true
      if (result.generation === this.generation && !this.gl.getQueryParameter(result.query, this.gl.QUERY_RESULT)) {
        this.hidden.add(result.key)
      }
      this.gl.deleteQuery(result.query)
      return false
    })
  }

  isHidden(key: string) { return this.hidden.has(key) }

  probe(camera: THREE.PerspectiveCamera, candidates: { key: string; box: THREE.Box3 }[],
    occluders: THREE.Points[], now: number) {
    if (!this.gl.createQuery || now - this.lastProbe < 250 || this.pending.length || !occluders.length) return
    const selected = candidates.filter(({ key, box }) => !this.tested.has(key)
      && !box.containsPoint(camera.position)
      // Near-plane intersections can invalidate a conservative bounding-box test.
      && box.distanceToPoint(camera.position) > camera.near * 2).slice(0, 8)
    if (!selected.length) return
    this.lastProbe = now
    const renderer = this.renderer
    const size = renderer.getDrawingBufferSize(new THREE.Vector2())
    this.target.setSize(size.x, size.y)
    const depthScene = new THREE.Scene()
    for (const source of occluders) {
      const proxy = new THREE.Points(source.geometry, source.material)
      proxy.matrixAutoUpdate = false
      proxy.matrix.copy(source.matrixWorld)
      depthScene.add(proxy)
    }
    const previousTarget = renderer.getRenderTarget()
    const previousAutoClear = renderer.autoClear
    const clearColor = renderer.getClearColor(new THREE.Color())
    const clearAlpha = renderer.getClearAlpha()
    try {
      renderer.setRenderTarget(this.target)
      renderer.autoClear = true
      renderer.render(depthScene, camera)
      renderer.autoClear = false
      const probes = new THREE.Scene()
      for (const { key, box } of selected) {
        const query = this.gl.createQuery()
        if (!query) continue
        this.tested.add(key)
        const mesh = new THREE.Mesh(this.boxGeometry, this.boxMaterial)
        box.getCenter(mesh.position)
        box.getSize(mesh.scale).addScalar(0.00001)
        mesh.frustumCulled = false
        mesh.onBeforeRender = () => this.gl.beginQuery(this.gl.ANY_SAMPLES_PASSED_CONSERVATIVE, query)
        mesh.onAfterRender = () => this.gl.endQuery(this.gl.ANY_SAMPLES_PASSED_CONSERVATIVE)
        probes.add(mesh)
        this.pending.push({ key, query, generation: this.generation })
      }
      renderer.render(probes, camera)
    } finally {
      renderer.setRenderTarget(previousTarget)
      renderer.autoClear = previousAutoClear
      renderer.setClearColor(clearColor, clearAlpha)
    }
  }

  dispose() {
    this.pending.forEach(({ query }) => this.gl.deleteQuery(query))
    this.pending = []
    this.target.dispose()
    this.boxGeometry.dispose()
    this.boxMaterial.dispose()
  }
}
