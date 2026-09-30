import * as THREE from 'three'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PcdSceneTileManifest } from '../../types/pcdMap'

const mocks = vi.hoisted(() => ({ load: vi.fn(), fetch: vi.fn(), instances: [] as { pointBudget: number; maxNumNodesLoading: number }[] }))
vi.mock('potree-core', () => ({
  Potree: class {
    pointBudget = 1000000
    maxNumNodesLoading = 4
    lru = { numPoints: 0 }
    constructor() { mocks.instances.push(this) }
    loadPointCloud = mocks.load
    updatePointClouds() { return { exceededMaxLoadsToGPU: false, nodeLoadPromises: [] } }
  },
}))
vi.mock('../../api/apiFetch', () => ({ fetchWithAuth: mocks.fetch }))
import { PotreeSceneManager } from './PotreeSceneManager'

describe('Potree original-only adapter', () => {
  afterEach(() => vi.unstubAllGlobals())
  it('keeps unlimited retention and original detail throughout following', async () => {
    const realLoad = vi.fn(async () => undefined)
    const cloud = Object.assign(new THREE.Group(), {
      minNodePixelSize: 100, maxLevel: 5, visibleNodes: [], dispose: vi.fn(),
      pcoGeometry: { numNodesLoading: 0, maxNumNodesLoading: 4,
        root: { traverse: vi.fn() }, loader: { load: realLoad, workerPool: { getWorker: vi.fn() } } },
    })
    mocks.load.mockResolvedValue(cloud)
    const bounds = { min_x: 0, max_x: 10, min_y: 0, max_y: 10, min_z: 0, max_z: 10 }
    const manifest = { bounds, layer_bounds: { wall: bounds }, stats: {},
      potree: { layers: [{ role: 'wall', url: '/metadata.json', point_count: 100_000_000_000, coordinate_scale: 1e-6 }] },
    } as unknown as PcdSceneTileManifest
    const stats = vi.fn()
    const camera = new THREE.PerspectiveCamera()
    const manager = new PotreeSceneManager({ manifest, camera, group: new THREE.Group(),
      renderer: { getContext: () => ({}), getPixelRatio: () => 1, domElement: { height: 720 } } as unknown as THREE.WebGLRenderer,
      wallColorMode: 'solid', visibleRoles: new Set(['wall']), onStats: stats, onInvalidate: vi.fn(),
    })
    await vi.waitFor(() => expect(stats).toHaveBeenCalled())
    const fetch = (mocks.load.mock.calls.at(-1) as unknown[])[1] as {
      fetch: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    }
    vi.stubGlobal('AbortSignal', Object.assign(Object.create(AbortSignal), {
      any: (signals: AbortSignal[]) => signals[0],
    }))
    mocks.fetch.mockResolvedValue(new Response(Uint8Array.from([0, 1, 2, 3]), {
      headers: { 'Content-Length': '4' },
    }))
    vi.stubGlobal('Headers', class {
      values: Record<string, string>
      constructor(values: Record<string, string>) { this.values = values }
      get(name: string) { return this.values[name] ?? null }
    })
    const [first, second] = await Promise.all([
      fetch.fetch('/hierarchy.bin', { headers: { Range: 'bytes=0-1' } }),
      fetch.fetch('/hierarchy.bin', { headers: { Range: 'bytes=2-3' } }),
    ])
    expect([...new Uint8Array(await first.arrayBuffer())]).toEqual([0, 1])
    expect([...new Uint8Array(await second.arrayBuffer())]).toEqual([2, 3])
    expect(mocks.fetch).toHaveBeenCalledTimes(1)
    for (let i = 1; i <= 200; i++) {
      camera.position.x += 0.02
      manager.update(false, i * 50, true)
    }
    expect(mocks.instances.at(-1)?.pointBudget).toBe(Infinity)
    expect(cloud.minNodePixelSize).toBe(0)
    expect(cloud.maxLevel).toBe(Infinity)
    expect(cloud.pcoGeometry.maxNumNodesLoading).toBeGreaterThan(0)
    manager.setVisibleRoles(new Set())
    expect(cloud.visible).toBe(false)
    manager.dispose()
    expect(cloud.dispose).toHaveBeenCalledOnce()
  })
})
