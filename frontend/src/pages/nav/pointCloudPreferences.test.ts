import { beforeEach, expect, it } from 'vitest'
import { loadPointCloudPreferences, loadSceneHeightClip, savePointCloudPreferences, saveSceneHeightClip } from './pointCloudPreferences'

beforeEach(() => window.localStorage.clear())

it('restores display preferences after a new read', () => {
  const chosen = {
    pointSize: 2.4,
    intensityPreference: -0.37,
    wallColorMode: 'height' as const,
    pointCloudQualityMode: 'quality' as const,
    pcdLayerVisibility: { map: true, ground: false, footprint: true },
  }
  savePointCloudPreferences(chosen)
  expect(loadPointCloudPreferences()).toEqual(chosen)
})

it('rejects invalid stored values and keeps height clips separate by scene', () => {
  window.localStorage.setItem('botdog-pcd-view-preferences:v1', JSON.stringify({
    pointSize: 99, intensityPreference: 'red', wallColorMode: 'unknown',
  }))
  expect(loadPointCloudPreferences()).toMatchObject({
    pointSize: 1, intensityPreference: 0, wallColorMode: 'intensity',
  })
  saveSceneHeightClip('scene-a', { min: 0.2, max: 2.6 })
  expect(loadSceneHeightClip('scene-a')).toEqual({ min: 0.2, max: 2.6 })
  expect(loadSceneHeightClip('scene-b')).toEqual({ min: null, max: null })
})
