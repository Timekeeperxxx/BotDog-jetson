import { describe, expect, it } from 'vitest'
import { getPointCount, getPointXYZ } from './pointCloudPoints'

describe('point cloud point containers', () => {
  it('reads tuple points', () => {
    const points: [number, number, number][] = [[1, 2, 3], [4, 5, 6]]
    expect(getPointCount(points)).toBe(2)
    expect(getPointXYZ(points, 1)).toEqual({ x: 4, y: 5, z: 6 })
  })

  it('reads packed Float32 XYZ points', () => {
    const points = new Float32Array([1, 2, 3, 4, 5, 6])
    expect(getPointCount(points)).toBe(2)
    expect(getPointXYZ(points, 1)).toEqual({ x: 4, y: 5, z: 6 })
  })
})
