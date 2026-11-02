import * as THREE from 'three'
import { mapToThree } from '../../utils/pointCloudTransform'
import { createWaypointLabelSprite } from './PointCloud3DViewerUtils'

export type MapRegionOverlay = { id: number | string; name: string; access_level: number | null; enabled: boolean | number; vertices: number[][] }

export function createMapRegionOverlay(region: MapRegionOverlay): THREE.Group {
  const group = new THREE.Group()
  const vertices = region.vertices
  if (!vertices.length) return group
  const colors: Record<number, number> = { 1: 0xf87171, 2: 0xfbbf24, 3: 0x22d3ee }
  const color = region.enabled ? colors[region.access_level ?? 0] ?? 0x94a3b8 : 0x64748b
  const points = vertices.map(([x, y, z]) => { const p = mapToThree(x, y, z + .08); return new THREE.Vector3(p.x, p.y, p.z) })
  const outline = new (points.length >= 3 ? THREE.LineLoop : THREE.Line)(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineBasicMaterial({ color, transparent: true, opacity: region.enabled ? 1 : .45, depthTest: false }))
  outline.renderOrder = 54; group.add(outline)
  if (vertices.length >= 3) {
    const triangles = THREE.ShapeUtils.triangulateShape(vertices.map(([x, y]) => new THREE.Vector2(x, y)), [])
    const positions = triangles.flatMap(triangle => triangle.flatMap(i => points[i].toArray()))
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    const fill = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: region.enabled ? .12 : .04, depthTest: false, depthWrite: false, side: THREE.DoubleSide }))
    fill.renderOrder = 51; group.add(fill)
  }
  const label = createWaypointLabelSprite(`${region.name} · ${region.access_level ? `${region.access_level}级` : '未设置级别'}${region.enabled ? '' : ' · 停用'}`, true)
  if (label) {
    const center = points.reduce((sum, p) => sum.add(p), new THREE.Vector3()).divideScalar(points.length)
    label.position.copy(center); label.position.y += .25; label.renderOrder = 55
    label.userData.adaptiveSprite = { pixels: 150 * label.scale.x / 2.8, baseWidth: label.scale.x, baseScale: label.scale.clone(), minScale: .05, maxScale: 120 }
    group.add(label)
  }
  return group
}
