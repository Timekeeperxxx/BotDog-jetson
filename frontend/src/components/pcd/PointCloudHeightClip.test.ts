import { expect, it } from 'vitest'
import { heightIntersects, setMaterialHeightClip } from './PointCloudHeightClip'
import { createPointCloudMaterial, getLayerPreset } from './PointCloud3DViewerUtils'
it('skips wholly outside blocks, retains crossing blocks and inclusive boundaries', () => {
  const clip = { min: 0, max: 10 }
  expect(heightIntersects(11, 14, clip)).toBe(false)
  expect(heightIntersects(-4, -1, clip)).toBe(false)
  expect(heightIntersects(9, 14, clip)).toBe(true)
  expect(heightIntersects(10, 10, clip)).toBe(true)
  expect(heightIntersects(-100, 100, { min: null, max: null })).toBe(true)
})
it('changes clipping uniforms without replacing point data or recompiling material', () => {
  const material = createPointCloudMaterial(getLayerPreset('wall'), 1)
  const version = material.version
  setMaterialHeightClip(material, { min: null, max: 10 })
  expect(material.uniforms.uHeightClip.value.y).toBe(10)
  setMaterialHeightClip(material, { min: null, max: null })
  expect(material.uniforms.uHeightClip.value.y).toBe(1e30)
  expect(material.version).toBe(version)
  material.dispose()
})
