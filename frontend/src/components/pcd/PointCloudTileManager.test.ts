import { afterEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import type { PcdSceneTileManifest } from '../../types/pcdMap'

const { getPcdSceneTile } = vi.hoisted(() => ({
  getPcdSceneTile: vi.fn(
    async (_sceneId: string, file: string) => {
      const hasIntensity = file.includes('wall')
      const pointCount = file.includes('performance')
        ? 1
        : file.includes('balanced')
          ? 2
          : hasIntensity ? 4 : 3
      return new ArrayBuffer(pointCount * (hasIntensity ? 13 : 12))
    },
  ),
}))

vi.mock('../../api/pcdMapApi', () => ({
  getPcdSceneTile,
}))

import { PointCloudTileManager } from './PointCloudTileManager'
import { getLayerPreset } from './PointCloud3DViewerUtils'

const bounds = {
  min_x: -1,
  max_x: 1,
  min_y: -1,
  max_y: 1,
  min_z: -1,
  max_z: 1,
}

const manifest: PcdSceneTileManifest = {
  version: 2,
  cache_key: 'scene-cache',
  scene_id: 'scene-1',
  frame_id: 'map',
  bounds,
  layer_bounds: { ground: bounds, wall: bounds, footprint_fill: null },
  root_tiles: [{
    id: 'ground-root',
    role: 'ground',
    bounds,
    file: 'ground.root.bin',
    point_count: 1,
    byte_length: 12,
    has_intensity: false,
  }],
  nodes: [
    {
      id: 'ground-1',
      role: 'ground',
      bounds,
      center: [0, 0, 0],
      radius: 1,
      performance: { file: 'ground.performance.bin', point_count: 1, byte_length: 12, has_intensity: false },
      balanced: { file: 'ground.balanced.bin', point_count: 2, byte_length: 24, has_intensity: false },
      original: { file: 'ground.original.bin', point_count: 3, byte_length: 36, has_intensity: false },
    },
    {
      id: 'wall-1',
      role: 'wall',
      bounds,
      center: [0, 0, 0],
      radius: 1,
      performance: { file: 'wall.performance.bin', point_count: 1, byte_length: 13, has_intensity: true },
      balanced: { file: 'wall.balanced.bin', point_count: 2, byte_length: 26, has_intensity: true },
      original: { file: 'wall.original.bin', point_count: 4, byte_length: 52, has_intensity: true },
    },
  ],
  stats: {},
  settings: {
    tile_size_m: 16,
    balanced_ratio: 0.5,
    performance_max_points: 180000,
    max_points_per_tile: 65_536,
  },
}

describe('PointCloudTileManager', () => {
  afterEach(() => {
    getPcdSceneTile.mockClear()
  })

  it('keeps the new requests intact after a rapid A to B to A density switch', async () => {
    const originalImplementation = getPcdSceneTile.getMockImplementation()!
    const replies: ((buffer: ArrayBuffer) => void)[] = []
    getPcdSceneTile.mockImplementation(() => new Promise(resolve => replies.push(resolve)))
    const manager = new PointCloudTileManager({
      manifest, camera: new THREE.PerspectiveCamera(), group: new THREE.Group(),
      renderer: { getPixelRatio: () => 1, domElement: { clientHeight: 600, height: 600 } } as THREE.WebGLRenderer,
      wallColorMode: 'solid', qualityMode: 'auto',
      visibleRoles: new Set(['ground', 'wall']), onStats: vi.fn(), onInvalidate: vi.fn(),
    })
    try {
      manager.setQualityMode('performance')
      manager.setQualityMode('auto')
      expect(getPcdSceneTile).toHaveBeenCalledTimes(6)
      replies[0](new ArrayBuffer(0))
      replies[1](new ArrayBuffer(0))
      await new Promise(resolve => setTimeout(resolve, 0))
      expect(getPcdSceneTile).toHaveBeenCalledTimes(6)
    } finally {
      manager.dispose()
      for (const resolve of replies) resolve(new ArrayBuffer(0))
      getPcdSceneTile.mockImplementation(originalImplementation)
    }
  })

  it('loads one fixed density tier and keeps it visible while the camera moves', async () => {
    const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100)
    camera.position.set(0, 0, 5)
    camera.lookAt(0, 0, 0)
    camera.updateProjectionMatrix()
    camera.updateMatrixWorld()
    const group = new THREE.Group()
    const onStats = vi.fn()
    const manager = new PointCloudTileManager({
      manifest,
      camera,
      renderer: { getPixelRatio: () => 1, domElement: { clientHeight: 600, height: 600 } } as THREE.WebGLRenderer,
      group,
      wallColorMode: 'solid',
      qualityMode: 'auto',
      visibleRoles: new Set(['ground', 'wall']),
      onStats,
      onInvalidate: vi.fn(),
    })

    await vi.waitFor(() => expect(group.children).toHaveLength(2))
    expect(getPcdSceneTile.mock.calls.map((call) => call[1]).sort()).toEqual([
      'ground.balanced.bin',
      'wall.balanced.bin',
    ])
    expect(group.children.every((cloud) => cloud.visible)).toBe(true)

    camera.position.set(5, 2, 0)
    camera.lookAt(0, 0, 0)
    camera.updateMatrixWorld()
    manager.update(true, performance.now() + 1_000)

    expect(group.children).toHaveLength(2)
    expect(group.children.every((cloud) => cloud.visible)).toBe(true)
    expect(getPcdSceneTile).toHaveBeenCalledTimes(2)
    expect(onStats.mock.calls.at(-1)?.[0]).toMatchObject({
      phase: 'ready',
      loadedPoints: 4,
      totalPoints: 4,
    })

    manager.dispose()
  })

  it('loads every original point only after the user selects the original tier', async () => {
    const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100)
    camera.position.set(0, 0, 5)
    camera.lookAt(0, 0, 0)
    camera.updateProjectionMatrix()
    camera.updateMatrixWorld()
    const group = new THREE.Group()
    const onStats = vi.fn()
    const manager = new PointCloudTileManager({
      manifest,
      camera,
      renderer: { getPixelRatio: () => 1, domElement: { clientHeight: 600, height: 600 } } as THREE.WebGLRenderer,
      group,
      wallColorMode: 'solid',
      qualityMode: 'auto',
      visibleRoles: new Set(['ground', 'wall']),
      onStats,
      onInvalidate: vi.fn(),
    })
    await vi.waitFor(() => expect(group.children).toHaveLength(2))

    manager.setQualityMode('quality')
    await vi.waitFor(() => expect(group.children).toHaveLength(2))

    expect(getPcdSceneTile.mock.calls.map((call) => call[1])).toEqual(expect.arrayContaining([
      'ground.original.bin',
      'wall.original.bin',
    ]))
    expect(onStats.mock.calls.at(-1)?.[0]).toMatchObject({
      phase: 'ready',
      loadedPoints: 7,
      totalPoints: 7,
    })

    manager.dispose()
  })
  it('updates loaded tiles and uses the current density for subsequently loaded tiles', async () => {
    const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100)
    camera.position.set(0, 0, 5)
    camera.lookAt(0, 0, 0)
    camera.updateMatrixWorld()
    let pixelRatio = 1.25
    const renderer = {
      getPixelRatio: () => pixelRatio,
      domElement: { clientHeight: 600, height: 750 },
    } as THREE.WebGLRenderer
    const group = new THREE.Group()
    const manager = new PointCloudTileManager({
      manifest, camera, renderer, group,
      wallColorMode: 'solid', qualityMode: 'auto',
      visibleRoles: new Set(['ground', 'wall']),
      onStats: vi.fn(), onInvalidate: vi.fn(),
    })
    const checkMaterials = () => {
      for (const object of group.children) {
        const cloud = object as THREE.Points<THREE.BufferGeometry, THREE.ShaderMaterial>
        expect(cloud.material.uniforms.uPixelRatio.value).toBe(pixelRatio)
        expect(cloud.material.uniforms.uViewportHeight.value).toBe(renderer.domElement.height)
        expect(cloud.material.uniforms.uNearSize.value).toBe(getLayerPreset(cloud.userData.role).nearSize)
      }
    }
    await vi.waitFor(() => expect(group.children).toHaveLength(2))
    checkMaterials()
    const originalTiles = [...group.children]
    pixelRatio = 2
    renderer.domElement.height = 1200
    manager.setViewport(1200, pixelRatio)
    checkMaterials()
    expect(group.children).toEqual(originalTiles)
    expect(getPcdSceneTile).toHaveBeenCalledTimes(2)

    manager.setQualityMode('quality')
    await vi.waitFor(() => expect(group.children).toHaveLength(2))
    checkMaterials()
    manager.dispose()
  })

})
