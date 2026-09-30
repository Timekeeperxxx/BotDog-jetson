import * as THREE from 'three'
import type { PcdSceneLayerRole, PointCloudPoints, WallColorMode } from '../../types/pcdMap'

export type PointCloudLayer = {
  role: PcdSceneLayerRole
  points: PointCloudPoints
  intensity?: Uint8Array
}

export const WAYPOINT_COLOR = 0xfbbf24
export const ROBOT_BODY_COLOR = 0xf97316
export const ROBOT_ARROW_COLOR = 0xf97316
export const WAYPOINT_RADIUS = 0.28
export const WAYPOINT_ARROW_LENGTH = 1.15
export const WAYPOINT_ARROW_HEAD_LENGTH = 0.34
export const WAYPOINT_ARROW_HEAD_WIDTH = 0.22
export const ROBOT_RADIUS = 0.34
export const ROBOT_HEIGHT = 0.26
export const ROBOT_ARROW_LENGTH = 1.1
export const ROBOT_ARROW_HEAD_LENGTH = 0.34
export const ROBOT_ARROW_HEAD_WIDTH = 0.22
// Keep these in sync with Navigation/src/nav_bringup/config/scan_planner.yaml.
// The two circle centres sit 0.205 m ahead of and behind base_footprint;
// their midpoint is the robot pose, and each has a 0.27 m radius.
export const SCAN_BODY_CYLINDER_RADIUS = 0.27
export const SCAN_BODY_CYLINDER_HEIGHT = 0.43
export const SCAN_BODY_CYLINDER_CENTER_Z_OFFSET = -0.115
export const SCAN_BODY_CYLINDER_OFFSETS = [0.205, -0.205] as const
export const GLOBAL_PATH_WIDTH = 0.12
export const WAYPOINT_SCREEN_DIAMETER_PX = 13
export const WAYPOINT_LABEL_SCREEN_WIDTH_PX = 112
export const ROBOT_SCREEN_DIAMETER_PX = 28
export const PENDING_TARGET_SCREEN_DIAMETER_PX = 22
export const POINT_CLOUD_MIN_ORBIT_DISTANCE = 0.05

type PointCloudMaterialPreset = {
  color: number
  heightGradient?: {
    lowColor: number
    middleColor: number
    highColor: number
    contourSpacing: number
    contourStrength: number
    farBrightness: number
  }
  nearSize: number
  farSize: number
  nearDistance: number
  farDistance: number
  worldPointSize: number
  maxPointSize: number
  opacity: number
  depthWrite: boolean
  opaqueSurface?: boolean
  renderOrder: number
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

export function getAdaptiveCameraNear(orbitDistance: number) {
  return clamp(orbitDistance / 1000, 0.005, 0.25)
}

export function shouldShowOrbitPivotMarker(pivotAvailable: boolean, cameraMoving: boolean) {
  return pivotAvailable && cameraMoving
}

export function createOrbitPivotMarker() {
  const marker = new THREE.Group()
  const coreGeometry = new THREE.OctahedronGeometry(0.08, 0)
  const coreMaterial = new THREE.MeshBasicMaterial({
    color: 0xff5a1f,
    transparent: true,
    opacity: 1,
    depthTest: false,
    depthWrite: false,
  })
  const core = new THREE.Mesh(coreGeometry, coreMaterial)
  core.renderOrder = 96
  marker.add(core)

  const crossGeometry = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(-0.24, 0, 0),
    new THREE.Vector3(0.24, 0, 0),
    new THREE.Vector3(0, -0.24, 0),
    new THREE.Vector3(0, 0.24, 0),
    new THREE.Vector3(0, 0, -0.24),
    new THREE.Vector3(0, 0, 0.24),
  ])
  const cross = new THREE.LineSegments(
    crossGeometry,
    new THREE.LineBasicMaterial({
      color: 0xfff200,
      transparent: true,
      opacity: 1,
      depthTest: false,
      depthWrite: false,
    }),
  )
  cross.renderOrder = 95
  marker.add(cross)
  marker.renderOrder = 95
  marker.visible = false
  marker.userData.adaptiveScale = {
    pixels: 28,
    baseSize: 0.48,
    minScale: 0.02,
    maxScale: 200,
  }
  return marker
}

export function getWallHeightGradientBounds(
  sampledHeights: number[],
  fallbackMin: number,
  fallbackMax: number,
) {
  const finiteHeights = sampledHeights.filter(Number.isFinite).sort((left, right) => left - right)
  if (finiteHeights.length < 20) {
    return { min: fallbackMin, max: fallbackMax }
  }

  const lastIndex = finiteHeights.length - 1
  const min = finiteHeights[Math.floor(lastIndex * 0.05)]
  const max = finiteHeights[Math.ceil(lastIndex * 0.95)]
  if (!Number.isFinite(min) || !Number.isFinite(max) || max - min < 0.25) {
    return { min: fallbackMin, max: fallbackMax }
  }

  return { min, max }
}

function disposeMaterial(material: THREE.Material | THREE.Material[]) {
  if (Array.isArray(material)) {
    material.forEach((item) => item.dispose())
  } else {
    material.dispose()
  }
}

export function setMaterialDepth(
  material: THREE.Material | THREE.Material[],
  depthTest: boolean,
  depthWrite: boolean,
  transparent = false,
) {
  const materials = Array.isArray(material) ? material : [material]
  materials.forEach((item) => {
    item.depthTest = depthTest
    item.depthWrite = depthWrite
    if (transparent) {
      item.transparent = true
      item.opacity = 1
    }
  })
}

export function disposeObject3D(object: THREE.Object3D) {
  if (object instanceof THREE.Group) {
    object.children.forEach(disposeObject3D)
    return
  }

  if (object instanceof THREE.Mesh) {
    object.geometry.dispose()
    disposeMaterial(object.material)
    return
  }

  if (object instanceof THREE.Line) {
    object.geometry.dispose()
    disposeMaterial(object.material)
    return
  }

  if (object instanceof THREE.Points) {
    object.geometry.dispose()
    disposeMaterial(object.material)
    return
  }

  if (object instanceof THREE.Sprite) {
    const material = object.material
    material.map?.dispose()
    material.dispose()
    return
  }

  if (object instanceof THREE.ArrowHelper) {
    object.line.geometry.dispose()
    object.cone.geometry.dispose()
    disposeMaterial(object.line.material)
    disposeMaterial(object.cone.material)
    return
  }
}

export function createMapYawDirection(yaw: number) {
  return new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw)).normalize()
}

export function createWaypointLabelSprite(text: string) {
  const canvas = document.createElement('canvas')
  const width = 512
  const height = 128
  canvas.width = width
  canvas.height = height

  const ctx = canvas.getContext('2d')
  if (!ctx) return null

  ctx.clearRect(0, 0, width, height)
  ctx.fillStyle = 'rgba(7, 14, 20, 0.56)'
  ctx.strokeStyle = 'rgba(251, 191, 36, 0.28)'
  ctx.lineWidth = 4
  ctx.beginPath()
  ctx.roundRect(4, 4, width - 8, height - 8, 20)
  ctx.fill()
  ctx.stroke()

  ctx.fillStyle = 'rgba(248, 250, 252, 0.94)'
  ctx.font = 'bold 44px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, width / 2, height / 2)

  const texture = new THREE.CanvasTexture(canvas)
  texture.minFilter = THREE.LinearFilter
  texture.magFilter = THREE.LinearFilter

  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthTest: false,
  })
  const sprite = new THREE.Sprite(material)
  sprite.scale.set(2.8, 0.7, 1)
  sprite.center.set(0.5, 0)
  sprite.renderOrder = 38
  return sprite
}

// Local +X is map yaw zero. The notch sits behind the coordinate origin.
export function createCursorArrow(color: number, radius: number, renderOrder: number) {
  const group = new THREE.Group()
  for (const [scale, tint] of [[1.16, 0x0f172a], [1.07, 0xffffff], [0.88, color]]) {
    const shape = new THREE.Shape()
    shape.moveTo(radius, 0)
    shape.lineTo(-radius, radius * 0.72)
    shape.lineTo(-radius * 0.45, 0)
    shape.lineTo(-radius, -radius * 0.72)
    shape.closePath()
    const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({
      color: tint, side: THREE.DoubleSide, depthTest: false, depthWrite: false,
    }))
    mesh.rotation.x = -Math.PI / 2
    mesh.scale.setScalar(scale)
    mesh.position.y = 0.08 + group.children.length * 0.002
    mesh.renderOrder = renderOrder + group.children.length
    group.add(mesh)
  }
  return group
}

export function getLayerPreset(role: PcdSceneLayerRole): PointCloudMaterialPreset {
  if (role === 'ground') {
    return {
      color: 0x3b82f6,
      nearSize: 2,
      farSize: 3.2,
      nearDistance: 1.5,
      farDistance: 18,
      worldPointSize: 0.025,
      maxPointSize: 6,
      opacity: 1,
      opaqueSurface: true,
      depthWrite: false,
      renderOrder: 1,
    }
  }

  if (role === 'live') {
    return {
      color: 0xffb020,
      nearSize: 3.4,
      farSize: 4.6,
      nearDistance: 6,
      farDistance: 52,
      worldPointSize: 0,
      maxPointSize: 7,
      opacity: 0.94,
      depthWrite: false,
      renderOrder: 3,
    }
  }

  if (role === 'footprint_fill') {
    return {
      color: 0xffffff,
      nearSize: 1.8,
      farSize: 2.6,
      nearDistance: 4,
      farDistance: 42,
      worldPointSize: 0.02,
      maxPointSize: 5,
      opacity: 1,
      depthWrite: true,
      renderOrder: 2,
    }
  }

  if (role === 'mapping') {
    return {
      color: 0x67e8f9,
      nearSize: 1.9,
      farSize: 2.8,
      nearDistance: 4,
      farDistance: 48,
      worldPointSize: 0,
      maxPointSize: 5,
      opacity: 0.42,
      depthWrite: false,
      renderOrder: 2,
    }
  }

  return {
    color: 0xd8b874,
    heightGradient: {
      lowColor: 0x2563eb,
      middleColor: 0x22c55e,
      highColor: 0xf97316,
      contourSpacing: 0.5,
      contourStrength: 0.18,
      farBrightness: 0.9,
    },
    nearSize: 1.5,
    farSize: 2.2,
    nearDistance: 6,
    farDistance: 48,
    worldPointSize: 0.018,
    maxPointSize: 5,
    opacity: 1,
    depthWrite: true,
    renderOrder: 0,
  }
}

type PointCloudMaterialOptions = {
  minHeight?: number
  maxHeight?: number
  wallColorMode?: WallColorMode
  viewportHeight?: number
  pointSizeScale?: number
  intensityPreference?: number
  hasIntensity?: boolean
}

export function createPointCloudMaterial(
  preset: PointCloudMaterialPreset,
  pixelRatio: number,
  options: PointCloudMaterialOptions = {},
) {
  const color = new THREE.Color(preset.color)
  const gradient = preset.heightGradient
  const minHeight = Number.isFinite(options.minHeight) ? options.minHeight! : 0
  const maxHeight = Number.isFinite(options.maxHeight) ? options.maxHeight! : minHeight + 1
  const gradientEnabled = gradient && options.wallColorMode !== 'solid' ? 1 : 0
  const intensityEnabled = gradient && options.wallColorMode === 'intensity' && options.hasIntensity ? 1 : 0
  // Ground stays opaque but does not occlude the footprint annotation.
  // Walls write depth first, so both layers still respect obstacles.
  const opaqueDepthPoint = (preset.depthWrite || preset.opaqueSurface) && preset.opacity >= 0.9

  return new THREE.ShaderMaterial({
    defines: {
      USE_POINT_INTENSITY: options.hasIntensity ? 1 : 0,
      OPAQUE_DEPTH_POINT: opaqueDepthPoint ? 1 : 0,
    },
    uniforms: {
      uColor: { value: color },
      uLowColor: { value: new THREE.Color(gradient?.lowColor ?? preset.color) },
      uMiddleColor: { value: new THREE.Color(gradient?.middleColor ?? preset.color) },
      uHighColor: { value: new THREE.Color(gradient?.highColor ?? preset.color) },
      uMinHeight: { value: minHeight },
      uMaxHeight: { value: Math.max(maxHeight, minHeight + 0.001) },
      uGradientEnabled: { value: gradientEnabled },
      uIntensityEnabled: { value: intensityEnabled },
      uIntensityPreference: { value: options.intensityPreference ?? 0 },
      uHeightClip: { value: new THREE.Vector2(-1e30, 1e30) },
      uPointSizeScale: { value: options.pointSizeScale ?? 1 },
      uContourSpacing: { value: gradient?.contourSpacing ?? 1 },
      uContourStrength: { value: gradient?.contourStrength ?? 0 },
      uFarBrightness: { value: gradient?.farBrightness ?? 1 },
      uPixelRatio: { value: pixelRatio },
      uNearSize: { value: preset.nearSize },
      uFarSize: { value: preset.farSize },
      uNearDistance: { value: preset.nearDistance },
      uFarDistance: { value: preset.farDistance },
      uWorldPointSize: { value: preset.worldPointSize },
      uViewportHeight: { value: Math.max(1, options.viewportHeight ?? 1) },
      uMaxPointSize: { value: preset.maxPointSize },
      uOpacity: { value: preset.opacity },
    },
    vertexShader: `
      uniform float uPointSizeScale;
      uniform float uPixelRatio;
      uniform float uNearSize;
      uniform float uFarSize;
      uniform float uNearDistance;
      uniform float uFarDistance;
      uniform float uWorldPointSize;
      uniform float uViewportHeight;
      uniform float uMaxPointSize;
      uniform vec3 uColor;
      uniform vec3 uLowColor;
      uniform vec3 uMiddleColor;
      uniform vec3 uHighColor;
      uniform float uMinHeight;
      uniform float uMaxHeight;
      uniform float uGradientEnabled;
      uniform float uIntensityEnabled;
      uniform float uIntensityPreference;
      uniform float uContourSpacing;
      uniform float uContourStrength;
      uniform float uFarBrightness;
      varying float vWorldHeight;
      varying float vDistanceMix;
      varying vec3 vPointColor;
      #if USE_POINT_INTENSITY == 1
        attribute float intensity;
      #endif

      vec3 intensityColor(float value) {
        value = pow(clamp(value, 0.0, 1.0), exp2(-2.0 * uIntensityPreference));
        value = clamp((value - 0.1) / 0.8, 0.0, 1.0);
        if (value < 0.25) return mix(vec3(0.03, 0.08, 1.0), vec3(0.0, 0.9, 1.0), value * 4.0);
        if (value < 0.5) return mix(vec3(0.0, 0.9, 1.0), vec3(0.05, 1.0, 0.18), (value - 0.25) * 4.0);
        if (value < 0.75) return mix(vec3(0.05, 1.0, 0.18), vec3(1.0, 0.92, 0.0), (value - 0.5) * 4.0);
        return mix(vec3(1.0, 0.92, 0.0), vec3(1.0, 0.03, 0.0), (value - 0.75) * 4.0);
      }

      void main() {
        vWorldHeight = (modelMatrix * vec4(position, 1.0)).y;
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        float cameraDistance = length(mvPosition.xyz);
        vDistanceMix = smoothstep(uNearDistance, uFarDistance, cameraDistance);

        vPointColor = uColor;
        if (uGradientEnabled > 0.5) {
          float heightMix = clamp(
            ((modelMatrix * vec4(position, 1.0)).y - uMinHeight) / max(uMaxHeight - uMinHeight, 0.001),
            0.0,
            1.0
          );
          vec3 gradientColor;
          if (heightMix < 0.5) {
            gradientColor = mix(uLowColor, uMiddleColor, smoothstep(0.0, 0.5, heightMix));
          } else {
            gradientColor = mix(uMiddleColor, uHighColor, smoothstep(0.5, 1.0, heightMix));
          }

          float contourCycle = fract((modelMatrix * vec4(position, 1.0)).y / max(uContourSpacing, 0.001));
          float contourDistance = min(contourCycle, 1.0 - contourCycle);
          float contourLine = 1.0 - smoothstep(0.0, 0.12, contourDistance);
          float distanceBrightness = mix(1.0, uFarBrightness, vDistanceMix);
          gradientColor *= distanceBrightness * (1.0 - contourLine * uContourStrength);
          vPointColor = gradientColor;
        }
        #if USE_POINT_INTENSITY == 1
          if (uIntensityEnabled > 0.5) {
            vPointColor = intensityColor(intensity);
          }
        #endif

        float fixedPointSize = mix(uNearSize, uFarSize, vDistanceMix) * uPixelRatio;
        float projectedWorldSize = uWorldPointSize * uViewportHeight * projectionMatrix[1][1]
          / max(-2.0 * mvPosition.z, 0.01);
        gl_PointSize = min(max(fixedPointSize, projectedWorldSize), uMaxPointSize * uPixelRatio) * uPointSizeScale;
        gl_Position = projectionMatrix * mvPosition;
      }
    `,
    fragmentShader: `
      uniform vec2 uHeightClip;
      uniform float uOpacity;
      varying float vWorldHeight;
      varying float vDistanceMix;
      varying vec3 vPointColor;

      void main() {
        if (vWorldHeight < uHeightClip.x || vWorldHeight > uHeightClip.y) discard;
        vec2 pointCoord = gl_PointCoord - vec2(0.5);
        float radius = length(pointCoord);
        if (radius > 0.5) {
          discard;
        }

        #if OPAQUE_DEPTH_POINT == 1
          gl_FragColor = vec4(vPointColor, 1.0);
        #else
          float softEdge = 1.0 - smoothstep(0.36, 0.5, radius);
          float distanceOpacity = mix(0.82, 1.0, vDistanceMix);
          float alpha = uOpacity * distanceOpacity * softEdge;
          if (alpha < 0.06) {
            discard;
          }
          gl_FragColor = vec4(vPointColor, alpha);
        #endif
      }
    `,
    transparent: !opaqueDepthPoint,
    depthTest: true,
    depthWrite: preset.depthWrite,
  })
}

export function setPointCloudWallColorMode(
  material: THREE.Material | THREE.Material[],
  mode: WallColorMode,
) {
  const materials = Array.isArray(material) ? material : [material]
  materials.forEach((item) => {
    if (!(item instanceof THREE.ShaderMaterial)) return
    const gradientUniform = item.uniforms.uGradientEnabled
    if (gradientUniform) gradientUniform.value = mode === 'solid' ? 0 : 1
    const intensityUniform = item.uniforms.uIntensityEnabled
    const hasIntensity = Number(item.defines?.USE_POINT_INTENSITY) === 1
    if (intensityUniform) intensityUniform.value = mode === 'intensity' && hasIntensity ? 1 : 0
  })
}

export function setPointCloudViewport(
  material: THREE.Material | THREE.Material[],
  viewportHeight: number,
  pixelRatio: number,
) {
  const materials = Array.isArray(material) ? material : [material]
  materials.forEach((item) => {
    if (!(item instanceof THREE.ShaderMaterial)) return
    const uniform = item.uniforms.uViewportHeight
    if (uniform) uniform.value = Math.max(1, viewportHeight)
    const ratioUniform = item.uniforms.uPixelRatio
    if (ratioUniform) ratioUniform.value = pixelRatio
  })
}

export function softenGrid(grid: THREE.GridHelper) {
  const materials = Array.isArray(grid.material) ? grid.material : [grid.material]
  materials.forEach((material) => {
    material.transparent = true
    material.opacity = 0.16
    material.depthWrite = false
  })
}

function worldUnitsForScreenPixels(
  camera: THREE.PerspectiveCamera,
  renderer: THREE.WebGLRenderer,
  worldPosition: THREE.Vector3,
  pixels: number,
) {
  const height = Math.max(1, renderer.domElement.clientHeight)
  const cameraSpacePosition = worldPosition.clone().applyMatrix4(camera.matrixWorldInverse)
  const depth = Math.max(0.01, Math.abs(cameraSpacePosition.z))
  const visibleHeight = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * depth
  return visibleHeight * (pixels / height)
}

export function applyAdaptiveOverlayScale(
  object: THREE.Object3D,
  camera: THREE.PerspectiveCamera,
  renderer: THREE.WebGLRenderer,
) {
  const worldPosition = new THREE.Vector3()
  object.getWorldPosition(worldPosition)

  const adaptiveScale = object.userData.adaptiveScale as {
    pixels: number
    baseSize: number
    minScale: number
    maxScale: number
  } | undefined
  if (adaptiveScale) {
    const worldSize = worldUnitsForScreenPixels(camera, renderer, worldPosition, adaptiveScale.pixels)
    const scale = clamp(worldSize / adaptiveScale.baseSize, adaptiveScale.minScale, adaptiveScale.maxScale)
    object.scale.setScalar(scale)
  }

  const adaptiveSprite = object.userData.adaptiveSprite as {
    pixels: number
    baseWidth: number
    baseScale: THREE.Vector3
    minScale: number
    maxScale: number
  } | undefined
  if (adaptiveSprite) {
    const worldWidth = worldUnitsForScreenPixels(camera, renderer, worldPosition, adaptiveSprite.pixels)
    const scale = clamp(worldWidth / adaptiveSprite.baseWidth, adaptiveSprite.minScale, adaptiveSprite.maxScale)
    object.scale.copy(adaptiveSprite.baseScale).multiplyScalar(scale)
  }
}


// Each source segment becomes a flat rectangle; retain measured heights and corners.
export function createFlatPathGeometry(points: THREE.Vector3[], width: number) {
  const vertices: number[] = []
  for (let index = 1; index < points.length; index += 1) {
    const a = points[index - 1]
    const b = points[index]
    const dx = b.x - a.x
    const dz = b.z - a.z
    const length = Math.hypot(dx, dz)
    if (length < 1e-6 || ![a.x, a.y, a.z, b.x, b.y, b.z].every(Number.isFinite)) continue
    const ox = -dz / length * width / 2
    const oz = dx / length * width / 2
    vertices.push(
      a.x + ox, a.y, a.z + oz,
      a.x - ox, a.y, a.z - oz,
      b.x + ox, b.y, b.z + oz,
      a.x - ox, a.y, a.z - oz,
      b.x - ox, b.y, b.z - oz,
      b.x + ox, b.y, b.z + oz,
    )
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3))
  return geometry
}

export function setPointCloudIntensityPreference(material: THREE.Material | THREE.Material[], value: number) {
  for (const item of Array.isArray(material) ? material : [material]) {
    if (item instanceof THREE.ShaderMaterial && item.uniforms.uIntensityPreference) {
      item.uniforms.uIntensityPreference.value = THREE.MathUtils.clamp(value, -1, 1)
    }
  }
}

export function setPointCloudPointSize(material: THREE.Material | THREE.Material[], value: number) {
  for (const item of Array.isArray(material) ? material : [material]) {
    if (item instanceof THREE.ShaderMaterial && item.uniforms.uPointSizeScale) {
      item.uniforms.uPointSizeScale.value = THREE.MathUtils.clamp(value, .1, 3)
    }
  }
}
