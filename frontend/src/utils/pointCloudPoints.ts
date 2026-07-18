import type { PointCloudPoints } from '../types/pcdMap'

export function getPointCount(points: PointCloudPoints): number {
  return points instanceof Float32Array ? Math.floor(points.length / 3) : points.length
}

export function getPointXYZ(points: PointCloudPoints, index: number) {
  if (points instanceof Float32Array) {
    const offset = index * 3
    return {
      x: points[offset],
      y: points[offset + 1],
      z: points[offset + 2],
    }
  }

  const point = points[index]
  return { x: point[0], y: point[1], z: point[2] }
}
