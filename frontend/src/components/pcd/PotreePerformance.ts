/** Feedback acts on rendering detail, never on retained memory or total points. */
export class PotreePerformance {
  radius = 0
  frameMs = 1000 / 60
  private baseline = 1000 / 60
  private frames: number[] = []
  private costs: number[] = []
  private elapsed = 0
  private healthy = 0

  resetWindow() {
    this.frames = []; this.costs = []; this.elapsed = 0; this.healthy = 0
  }

  sample(delta: number, cost: number, active: boolean, stationary = false) {
    if (!active || delta <= 0 || delta > 250) { this.resetWindow(); return }
    this.frames.push(delta)
    this.costs.push(cost)
    this.elapsed += delta
    if (this.elapsed < (stationary ? 250 : 1000) || this.frames.length < 8) return
    const sorted = [...this.frames].sort((a, b) => a - b)
    // Only learn faster refresh rhythms, so a heavily loaded startup cannot
    // redefine sustained 20 fps as the screen's healthy baseline.
    this.baseline = Math.max(1000 / 240, Math.min(this.baseline, sorted[Math.floor(sorted.length * .1)]))
    this.frameMs = this.elapsed / this.frames.length
    const slow = this.frames.filter((v) => v > this.baseline * 1.45).length / this.frames.length
    const expensive = this.costs.filter((v) => v > this.baseline * .8).length / this.costs.length
    if (stationary && slow < .1 && expensive < .1) {
      this.radius = Math.max(0, this.radius - 2)
      this.healthy = 0
    } else if (this.elapsed < 1000) {
      return
    } else if (slow > .25 && expensive > .25) {
      // Maximum radius 24 corresponds approximately to one CSS pixel between
      // 2048 parent samples on a projected surface; never repeat the coarse 96px setting.
      this.radius = Math.min(24, this.radius + 1)
      this.healthy = 0
    } else if (slow < .1 && expensive < .1) {
      this.healthy++
      if (this.healthy >= 3) { this.radius = Math.max(0, this.radius - .5); this.healthy = 0 }
    } else this.healthy = 0
    this.frames = []; this.costs = []; this.elapsed = 0
  }
}

/** Asynchronous whole-scene GPU timing; no blocking readback, optional on unsupported GPUs. */
export class PotreeGpuTimer {
  private gl: WebGL2RenderingContext
  private extension: { TIME_ELAPSED_EXT: number; GPU_DISJOINT_EXT: number } | null
  private pending: WebGLQuery[] = []
  private current: WebGLQuery | null = null
  milliseconds = 0
  constructor(gl: WebGL2RenderingContext) {
    this.gl = gl
    this.extension = gl.getExtension?.('EXT_disjoint_timer_query_webgl2') ?? null
  }
  begin() {
    const gl = this.gl, ext = this.extension
    if (!ext || gl.isContextLost()) return
    const disjoint = gl.getParameter(ext.GPU_DISJOINT_EXT)
    this.pending = this.pending.filter((q) => {
      if (!disjoint && !gl.getQueryParameter(q, gl.QUERY_RESULT_AVAILABLE)) return true
      if (!disjoint) this.milliseconds = gl.getQueryParameter(q, gl.QUERY_RESULT) / 1e6
      gl.deleteQuery(q); return false
    })
    if (disjoint) this.milliseconds = 0
    if (this.pending.length >= 4 || gl.getQuery(ext.TIME_ELAPSED_EXT, gl.CURRENT_QUERY)) return
    this.current = gl.createQuery()
    if (this.current) gl.beginQuery(ext.TIME_ELAPSED_EXT, this.current)
  }
  end() {
    if (!this.current || !this.extension) return
    this.gl.endQuery(this.extension.TIME_ELAPSED_EXT)
    this.pending.push(this.current); this.current = null
  }
  dispose() {
    this.end(); this.pending.forEach((q) => this.gl.deleteQuery(q)); this.pending = []
  }
}
