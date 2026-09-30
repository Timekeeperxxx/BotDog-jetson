import type { PointCloudQualityMode, WallColorMode } from '../../types/pcdMap'
import type { HeightClip } from '../../components/pcd/PointCloudHeightClip'
import type { PcdLayerVisibility } from './NavToolStrip'

const STORAGE_KEY = 'botdog-pcd-view-preferences:v1'
const HEIGHT_KEY_PREFIX = 'botdog-pcd-height-clip:v1:'

export type PointCloudPreferences = {
  pointSize: number
  intensityPreference: number
  wallColorMode: WallColorMode
  pointCloudQualityMode: PointCloudQualityMode
  pcdLayerVisibility: PcdLayerVisibility
}

const defaults: PointCloudPreferences = {
  pointSize: 1,
  intensityPreference: 0,
  wallColorMode: 'intensity',
  pointCloudQualityMode: 'auto',
  pcdLayerVisibility: { map: true, ground: true, footprint: true },
}

export function loadPointCloudPreferences(): PointCloudPreferences {
  try {
    const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? 'null')
    if (!value || typeof value !== 'object') return defaults
    const layers = value.pcdLayerVisibility
    return {
      pointSize: typeof value.pointSize === 'number' && Number.isFinite(value.pointSize) && value.pointSize >= 0.1 && value.pointSize <= 3 ? value.pointSize : defaults.pointSize,
      intensityPreference: typeof value.intensityPreference === 'number' && Number.isFinite(value.intensityPreference) && value.intensityPreference >= -1 && value.intensityPreference <= 1 ? value.intensityPreference : defaults.intensityPreference,
      wallColorMode: value.wallColorMode === 'height' || value.wallColorMode === 'intensity' ? value.wallColorMode : defaults.wallColorMode,
      pointCloudQualityMode: value.pointCloudQualityMode === 'performance' || value.pointCloudQualityMode === 'quality' ? value.pointCloudQualityMode : defaults.pointCloudQualityMode,
      pcdLayerVisibility: {
        map: typeof layers?.map === 'boolean' ? layers.map : true,
        ground: typeof layers?.ground === 'boolean' ? layers.ground : true,
        footprint: typeof layers?.footprint === 'boolean' ? layers.footprint : true,
      },
    }
  } catch {
    return defaults
  }
}

export function savePointCloudPreferences(value: PointCloudPreferences): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  } catch {
    // Browser storage may be unavailable; the current page remains usable.
  }
}

export function loadSceneHeightClip(sceneId: string | null): HeightClip {
  if (!sceneId) return { min: null, max: null }
  try {
    const value = JSON.parse(window.localStorage.getItem(HEIGHT_KEY_PREFIX + encodeURIComponent(sceneId)) ?? 'null')
    const min = typeof value?.min === 'number' && Number.isFinite(value.min) ? value.min : null
    const max = typeof value?.max === 'number' && Number.isFinite(value.max) ? value.max : null
    return min !== null && max !== null && min > max ? { min: null, max: null } : { min, max }
  } catch {
    return { min: null, max: null }
  }
}

export function saveSceneHeightClip(sceneId: string, value: HeightClip): void {
  try {
    window.localStorage.setItem(HEIGHT_KEY_PREFIX + encodeURIComponent(sceneId), JSON.stringify(value))
  } catch {
    // Browser storage may be unavailable; the current page remains usable.
  }
}
