import { describe, expect, it } from 'vitest'
import type { PcdSceneRootTile } from '../../types/pcdMap'
import { decodeTopDownOverviewTile } from './useNavScenes'

const tile: PcdSceneRootTile = {
  id: 'wall-root',
  role: 'wall',
  bounds: { min_x: 1, max_x: 4, min_y: -6, max_y: -3, min_z: 2, max_z: 5 },
  file: 'wall.root.bin',
  point_count: 2,
  byte_length: 26,
  has_intensity: true,
}

describe('2D point-cloud overview tiles', () => {
  it('reuses the root tile position buffer without expanding it into objects', () => {
    const buffer = new ArrayBuffer(26)
    new Float32Array(buffer, 0, 6).set([1, 2, 3, 4, 5, 6])

    const layer = decodeTopDownOverviewTile(tile, buffer)

    expect(layer.coordinateSpace).toBe('three')
    expect(layer.points).toBeInstanceOf(Float32Array)
    expect(Array.from(layer.points as Float32Array)).toEqual([1, 2, 3, 4, 5, 6])
  })

  it('rejects truncated root tiles', () => {
    expect(() => decodeTopDownOverviewTile(tile, new ArrayBuffer(25))).toThrow(
      '2D 概览瓦片长度不匹配',
    )
  })
})
