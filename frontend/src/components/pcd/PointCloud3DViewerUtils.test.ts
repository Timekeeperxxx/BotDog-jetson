import { describe, expect, it } from 'vitest'
import {
  SCAN_BODY_CYLINDER_CENTER_Z_OFFSET,
  SCAN_BODY_CYLINDER_HEIGHT,
  SCAN_BODY_CYLINDER_OFFSETS,
  SCAN_BODY_CYLINDER_RADIUS,
  POINT_CLOUD_MIN_ORBIT_DISTANCE,
  WAYPOINT_LABEL_SCREEN_WIDTH_PX,
  createPointCloudMaterial,
  createOrbitPivotMarker,
  disposeObject3D,
  getAdaptiveCameraNear,
  getLayerPreset,
  getWallHeightGradientBounds,
  setPointCloudViewportHeight,
  setPointCloudWallColorMode,
  shouldShowOrbitPivotMarker,
} from './PointCloud3DViewerUtils'

describe('B2 SCAN collision-body overlay', () => {
  it('matches the Navigation double-cylinder footprint', () => {
    expect(SCAN_BODY_CYLINDER_RADIUS).toBe(0.25)
    expect(SCAN_BODY_CYLINDER_OFFSETS).toEqual([-0.225, -0.675])
    expect(SCAN_BODY_CYLINDER_HEIGHT).toBe(0.43)
    expect(SCAN_BODY_CYLINDER_CENTER_Z_OFFSET + SCAN_BODY_CYLINDER_HEIGHT / 2).toBeCloseTo(0.10)
    expect(SCAN_BODY_CYLINDER_CENTER_Z_OFFSET - SCAN_BODY_CYLINDER_HEIGHT / 2).toBeCloseTo(-0.33)
  })

  it('keeps waypoint labels legible at normal zoom', () => {
    expect(WAYPOINT_LABEL_SCREEN_WIDTH_PX).toBeGreaterThanOrEqual(100)
  })
})

describe('wall point-cloud coloring', () => {
  it('creates the height gradient with the layer height bounds', () => {
    const material = createPointCloudMaterial(getLayerPreset('wall'), 1, {
      minHeight: -0.4,
      maxHeight: 2.6,
      wallColorMode: 'height',
    })

    expect(material.uniforms.uGradientEnabled.value).toBe(1)
    expect(material.uniforms.uMinHeight.value).toBe(-0.4)
    expect(material.uniforms.uMaxHeight.value).toBe(2.6)
    expect(material.uniforms.uLowColor.value.getHex()).toBe(0x2563eb)
    expect(material.uniforms.uMiddleColor.value.getHex()).toBe(0x22c55e)
    expect(material.uniforms.uHighColor.value.getHex()).toBe(0xf97316)
    expect(material.uniforms.uContourSpacing.value).toBe(0.5)

    material.dispose()
  })

  it('ignores sparse height outliers when choosing the gradient range', () => {
    const representativeHeights = Array.from({ length: 100 }, (_, index) => index / 40)
    const bounds = getWallHeightGradientBounds(
      [-100, ...representativeHeights, 100],
      -100,
      100,
    )

    expect(bounds.min).toBeGreaterThan(-1)
    expect(bounds.max).toBeLessThan(4)
    expect(bounds.max - bounds.min).toBeGreaterThan(2)
  })

  it('switches modes by updating only the shader uniform', () => {
    const material = createPointCloudMaterial(getLayerPreset('wall'), 1, {
      wallColorMode: 'intensity',
      hasIntensity: true,
    })

    expect(material.uniforms.uIntensityEnabled.value).toBe(1)
    expect(material.defines.USE_POINT_INTENSITY).toBe(1)

    setPointCloudWallColorMode(material, 'solid')
    expect(material.uniforms.uGradientEnabled.value).toBe(0)
    expect(material.uniforms.uIntensityEnabled.value).toBe(0)

    setPointCloudWallColorMode(material, 'height')
    expect(material.uniforms.uGradientEnabled.value).toBe(1)
    expect(material.uniforms.uIntensityEnabled.value).toBe(0)

    setPointCloudWallColorMode(material, 'intensity')
    expect(material.uniforms.uIntensityEnabled.value).toBe(1)
    expect(material.vertexShader).toContain('intensityColor')

    material.dispose()
  })

  it('keeps non-wall presets on their solid color', () => {
    const material = createPointCloudMaterial(getLayerPreset('ground'), 1, {
      wallColorMode: 'height',
    })

    expect(material.uniforms.uGradientEnabled.value).toBe(0)
    material.dispose()
  })

  it('writes depth for static scene layers but not live mapping overlays', () => {
    const ground = createPointCloudMaterial(getLayerPreset('ground'), 1)
    const wall = createPointCloudMaterial(getLayerPreset('wall'), 1)
    const footprint = createPointCloudMaterial(getLayerPreset('footprint_fill'), 1)
    const mapping = createPointCloudMaterial(getLayerPreset('mapping'), 1)
    const live = createPointCloudMaterial(getLayerPreset('live'), 1)

    expect(ground.depthWrite).toBe(true)
    expect(wall.depthWrite).toBe(true)
    expect(footprint.depthWrite).toBe(true)
    expect(mapping.depthWrite).toBe(false)
    expect(live.depthWrite).toBe(false)
    expect(ground.transparent).toBe(false)
    expect(wall.transparent).toBe(false)
    expect(footprint.transparent).toBe(true)
    expect(mapping.transparent).toBe(true)
    expect(wall.defines.OPAQUE_DEPTH_POINT).toBe(1)
    expect(footprint.defines.OPAQUE_DEPTH_POINT).toBe(0)

    ground.dispose()
    wall.dispose()
    footprint.dispose()
    mapping.dispose()
    live.dispose()
  })

  it('projects a bounded world-space splat size for close zoom', () => {
    const material = createPointCloudMaterial(getLayerPreset('wall'), 1.5, {
      viewportHeight: 1080,
    })

    expect(material.uniforms.uWorldPointSize.value).toBe(0.018)
    expect(material.uniforms.uViewportHeight.value).toBe(1080)
    expect(material.uniforms.uMaxPointSize.value).toBe(7.5)
    expect(material.vertexShader).toContain('projectedWorldSize')
    expect(material.vertexShader).toContain('min(max(fixedPointSize, projectedWorldSize), uMaxPointSize)')

    setPointCloudViewportHeight(material, 720)
    expect(material.uniforms.uViewportHeight.value).toBe(720)
    material.dispose()
  })
})

describe('3D orbit focus', () => {
  it('allows close zoom while keeping a safe adaptive near plane', () => {
    expect(POINT_CLOUD_MIN_ORBIT_DISTANCE).toBe(0.05)
    expect(getAdaptiveCameraNear(0.05)).toBe(0.005)
    expect(getAdaptiveCameraNear(10)).toBe(0.01)
    expect(getAdaptiveCameraNear(1000)).toBe(0.25)
  })

  it('creates a fixed-screen-size marker for the orbit target', () => {
    const marker = createOrbitPivotMarker()

    expect(marker.visible).toBe(false)
    expect(marker.children).toHaveLength(2)
    expect(marker.userData.adaptiveScale.pixels).toBe(28)

    disposeObject3D(marker)
  })

  it('shows the orbit target only while the camera is moving', () => {
    expect(shouldShowOrbitPivotMarker(false, false)).toBe(false)
    expect(shouldShowOrbitPivotMarker(false, true)).toBe(false)
    expect(shouldShowOrbitPivotMarker(true, false)).toBe(false)
    expect(shouldShowOrbitPivotMarker(true, true)).toBe(true)
  })
})
