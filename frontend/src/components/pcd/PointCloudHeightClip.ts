import * as THREE from 'three'
export type HeightClip = { min: number | null; max: number | null }
export const NO_HEIGHT_CLIP: HeightClip = { min: null, max: null }
export function heightIntersects(low: number, high: number, clip: HeightClip) {
  return high >= (clip.min ?? -Infinity) && low <= (clip.max ?? Infinity)
}
export function setMaterialHeightClip(material: THREE.Material | THREE.Material[], clip: HeightClip) {
  for (const item of Array.isArray(material) ? material : [material]) {
    if (item instanceof THREE.ShaderMaterial && item.uniforms.uHeightClip) {
      item.uniforms.uHeightClip.value.set(clip.min ?? -1e30, clip.max ?? 1e30)
    }
  }
}
