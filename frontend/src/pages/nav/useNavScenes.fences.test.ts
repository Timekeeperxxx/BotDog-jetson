import { renderHook, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { useNavScenes } from './useNavScenes'
import type { NavFence } from '../../types/pcdMap'

vi.mock('../../api/navApi', () => ({ getNavState: vi.fn().mockResolvedValue({}) }))
vi.mock('../../api/pcdMapApi', () => ({
  listPcdScenes: vi.fn().mockResolvedValue({ root: '', items: [{ id: 'Scene1_测试', ready: true }] }),
  selectPcdScene: vi.fn().mockResolvedValue({ scene_id: 'Scene1_测试' }),
  getPcdSceneMetadata: vi.fn().mockResolvedValue({ scene_id: 'Scene1_测试' }),
  getPcdSceneTileManifest: vi.fn().mockResolvedValue({ root_tiles: [], nodes: [] }),
  getPcdScenePreview: vi.fn(),
  getPcdSceneTile: vi.fn(),
  listWaypoints: vi.fn().mockResolvedValue({ items: [] }),
  listFences: vi.fn().mockResolvedValue({ items: [{ id: 'saved-fence' }] }),
}))

it('restores saved fences after resetting the scene remembered across a page refresh', async () => {
  window.localStorage.setItem('botdog-nav-selected-scene', 'Scene1_测试')
  let visibleFences: NavFence[] = []
  const options = {
    setInitialState: vi.fn(),
    onWaypointsLoaded: vi.fn(),
    onLog: vi.fn(),
    onSceneChanging: vi.fn(() => { visibleFences = [] }),
    onFencesLoaded: vi.fn((fences: NavFence[]) => { visibleFences = fences }),
  }
  const { result, unmount } = renderHook(() => useNavScenes(options))
  await waitFor(() => expect(result.current.metadata?.scene_id).toBe('Scene1_测试'))
  await waitFor(() => expect(visibleFences).toEqual([{ id: 'saved-fence' }]))
  expect(options.onSceneChanging).toHaveBeenCalled()
  unmount()
  window.localStorage.clear()
})
