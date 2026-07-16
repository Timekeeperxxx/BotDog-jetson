import * as THREE from 'three'
import type { PcdSceneLayerRole } from '../../types/pcdMap'

export type PointCloudLayer = {
  role: PcdSceneLayerRole
  points: [number, number, number][]
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
export const POINT_CLOUD_PIXEL_RATIO_LIMIT = 1.5

type PointCloudMaterialPreset = {
  color: number
  nearSize: number
  farSize: number
  nearDistance: number
  farDistance: number
  opacity: number
  renderOrder: number
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

const POINT_DISPLAY_LIMIT_BY_ROLE: Partial<Record<PcdSceneLayerRole, number>> = {
  ground: 70000,
  footprint_fill: 50000,
  mapping: 25000,
  live: 1200,
}
const LIMITED_POINT_CACHE = new WeakMap<
  [number, number, number][],
  Partial<Record<PcdSceneLayerRole, [number, number, number][]>>
>()

export function limitDisplayPoints(
  role: PcdSceneLayerRole,
  points: [number, number, number][],
) {
  const limit = POINT_DISPLAY_LIMIT_BY_ROLE[role]
  if (!limit || points.length <= limit) return points

  const cached = LIMITED_POINT_CACHE.get(points)?.[role]
  if (cached) return cached

  const stride = Math.max(1, Math.ceil(points.length / limit))
  const limited = points.filter((_, index) => index % stride === 0).slice(0, limit)
  const cachedByRole = LIMITED_POINT_CACHE.get(points) ?? {}
  cachedByRole[role] = limited
  LIMITED_POINT_CACHE.set(points, cachedByRole)
  return limited
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
      nearSize: 3.8,
      farSize: 6.2,
      nearDistance: 1.5,
      farDistance: 18,
      opacity: 0.94,
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
      opacity: 0.94,
      renderOrder: 3,
    }
  }

  if (role === 'footprint_fill') {
    return {
      color: 0xffffff,
      nearSize: 2.6,
      farSize: 3.8,
      nearDistance: 4,
      farDistance: 42,
      opacity: 0.72,
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
      opacity: 0.42,
      renderOrder: 2,
    }
  }

  return {
    color: 0x22c55e,
    nearSize: 2.2,
    farSize: 2.8,
    nearDistance: 6,
    farDistance: 48,
    opacity: 0.62,
    renderOrder: 2,
  }
}

export function createPointCloudMaterial(preset: PointCloudMaterialPreset, pixelRatio: number) {
  const color = new THREE.Color(preset.color)

  return new THREE.ShaderMaterial({
    uniforms: {
      uColor: { value: color },
      uNearSize: { value: preset.nearSize * pixelRatio },
      uFarSize: { value: preset.farSize * pixelRatio },
      uNearDistance: { value: preset.nearDistance },
      uFarDistance: { value: preset.farDistance },
      uOpacity: { value: preset.opacity },
    },
    vertexShader: `
      uniform float uNearSize;
      uniform float uFarSize;
      uniform float uNearDistance;
      uniform float uFarDistance;
      varying float vDistanceMix;

      void main() {
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        float cameraDistance = length(mvPosition.xyz);
        vDistanceMix = smoothstep(uNearDistance, uFarDistance, cameraDistance);
        gl_PointSize = mix(uNearSize, uFarSize, vDistanceMix);
        gl_Position = projectionMatrix * mvPosition;
      }
    `,
    fragmentShader: `
      uniform vec3 uColor;
      uniform float uOpacity;
      varying float vDistanceMix;

      void main() {
        vec2 pointCoord = gl_PointCoord - vec2(0.5);
        float radius = length(pointCoord);
        if (radius > 0.5) {
          discard;
        }

        float softEdge = 1.0 - smoothstep(0.36, 0.5, radius);
        float distanceOpacity = mix(0.82, 1.0, vDistanceMix);
        gl_FragColor = vec4(uColor, uOpacity * distanceOpacity * softEdge);
      }
    `,
    transparent: true,
    depthTest: true,
    depthWrite: false,
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
