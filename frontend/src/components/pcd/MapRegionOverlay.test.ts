import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createMapRegionOverlay } from './MapRegionOverlay'
vi.mock('./PointCloud3DViewerUtils', () => ({ createWaypointLabelSprite: () => null }))

it.each([false, true])('fills a concave map region without covering the cut-out, reverse=%s', reverse => {
  // Software geometry fixture; no measured map or robot positions.
  const vertices = [[0,0,0],[4,0,0],[4,1,0],[1,1,0],[1,4,0],[0,4,0]]
  const group = createMapRegionOverlay({id:1,name:'软件测试区域',access_level:1,enabled:true,vertices:reverse ? [...vertices].reverse() : vertices})
  const fill = group.children.find(child => child instanceof THREE.Mesh) as THREE.Mesh<THREE.BufferGeometry>
  const positions = fill.geometry.getAttribute('position')
  let area = 0
  for (let i=0;i<positions.count;i+=3) {
    const ax=positions.getX(i), ay=positions.getZ(i), bx=positions.getX(i+1), by=positions.getZ(i+1), cx=positions.getX(i+2), cy=positions.getZ(i+2)
    area += Math.abs((bx-ax)*(cy-ay)-(by-ay)*(cx-ax))/2
  }
  expect(area).toBeCloseTo(7)
})
