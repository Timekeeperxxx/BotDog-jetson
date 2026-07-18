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
// Relative to the map -> base_footprint origin, the two circle centres are
// 0.225 m and 0.675 m behind the robot along its local x axis.
export const SCAN_BODY_CYLINDER_RADIUS = 0.25
export const SCAN_BODY_CYLINDER_HEIGHT = 0.43
export const SCAN_BODY_CYLINDER_CENTER_Z_OFFSET = -0.115
export const SCAN_BODY_CYLINDER_OFFSETS = [-0.225, -0.675] as const
export const GLOBAL_PATH_RADIUS = 0.06
export const GLOBAL_PATH_NODE_RADIUS = 0.06
export const WAYPOINT_SCREEN_DIAMETER_PX = 13
export const WAYPOINT_LABEL_SCREEN_WIDTH_PX = 112
export const ROBOT_SCREEN_DIAMETER_PX = 18
export const PENDING_TARGET_SCREEN_DIAMETER_PX = 13
export const POINT_CLOUD_PIXEL_RATIO_LIMIT = 1
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

export function getLayerPreset(role: PcdSceneLayerRole): PointCloudMaterialPreset {
  if (role === 'ground') {
    return {
      color: 0x0ea5e9,
      nearSize: 2,
      farSize: 3.2,
      nearDistance: 1.5,
      farDistance: 18,
      worldPointSize: 0.025,
      maxPointSize: 6,
      opacity: 1,
      depthWrite: true,
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
      opacity: 0.72,
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
    color: 0x22c55e,
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
    renderOrder: 2,
  }
}

type PointCloudMaterialOptions = {
  minHeight?: number
  maxHeight?: number
  wallColorMode?: WallColorMode
  viewportHeight?: number
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
  const opaqueDepthPoint = preset.depthWrite && preset.opacity >= 0.9

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
      uContourSpacing: { value: gradient?.contourSpacing ?? 1 },
      uContourStrength: { value: gradient?.contourStrength ?? 0 },
      uFarBrightness: { value: gradient?.farBrightness ?? 1 },
      uNearSize: { value: preset.nearSize * pixelRatio },
      uFarSize: { value: preset.farSize * pixelRatio },
      uNearDistance: { value: preset.nearDistance },
      uFarDistance: { value: preset.farDistance },
      uWorldPointSize: { value: preset.worldPointSize },
      uViewportHeight: { value: Math.max(1, options.viewportHeight ?? 1) },
      uMaxPointSize: { value: preset.maxPointSize * pixelRatio },
      uOpacity: { value: preset.opacity },
    },
    vertexShader: `
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
      uniform float uContourSpacing;
      uniform float uContourStrength;
      uniform float uFarBrightness;
      varying float vDistanceMix;
      varying vec3 vPointColor;
      #if USE_POINT_INTENSITY == 1
        attribute float intensity;
      #endif

      vec3 intensityColor(float value) {
        if (value < 0.25) {
          return mix(vec3(0.03, 0.08, 1.0), vec3(0.0, 0.9, 1.0), value * 4.0);
        }
        if (value < 0.5) {
          return mix(vec3(0.0, 0.9, 1.0), vec3(0.05, 1.0, 0.18), (value - 0.25) * 4.0);
        }
        if (value < 0.75) {
          return mix(vec3(0.05, 1.0, 0.18), vec3(1.0, 0.92, 0.0), (value - 0.5) * 4.0);
        }
        return mix(vec3(1.0, 0.92, 0.0), vec3(1.0, 0.03, 0.0), (value - 0.75) * 4.0);
      }

      void main() {
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        float cameraDistance = length(mvPosition.xyz);
        vDistanceMix = smoothstep(uNearDistance, uFarDistance, cameraDistance);

        vPointColor = uColor;
        if (uGradientEnabled > 0.5) {
          float heightMix = clamp(
            (position.y - uMinHeight) / max(uMaxHeight - uMinHeight, 0.001),
            0.0,
            1.0
          );
          vec3 gradientColor;
          if (heightMix < 0.5) {
            gradientColor = mix(uLowColor, uMiddleColor, smoothstep(0.0, 0.5, heightMix));
          } else {
            gradientColor = mix(uMiddleColor, uHighColor, smoothstep(0.5, 1.0, heightMix));
          }

          float contourCycle = fract(position.y / max(uContourSpacing, 0.001));
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

        float fixedPointSize = mix(uNearSize, uFarSize, vDistanceMix);
        float projectedWorldSize = uWorldPointSize * uViewportHeight * projectionMatrix[1][1]
          / max(-2.0 * mvPosition.z, 0.01);
        gl_PointSize = min(max(fixedPointSize, projectedWorldSize), uMaxPointSize);
        gl_Position = projectionMatrix * mvPosition;
      }
    `,
    fragmentShader: `
      uniform float uOpacity;
      varying float vDistanceMix;
      varying vec3 vPointColor;

      void main() {
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

export function setPointCloudViewportHeight(
  material: THREE.Material | THREE.Material[],
  viewportHeight: number,
) {
  const materials = Array.isArray(material) ? material : [material]
  materials.forEach((item) => {
    if (!(item instanceof THREE.ShaderMaterial)) return
    const uniform = item.uniforms.uViewportHeight
    if (uniform) uniform.value = Math.max(1, viewportHeight)
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
