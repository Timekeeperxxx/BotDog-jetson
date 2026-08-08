import { describe, expect, it, vi } from 'vitest'
import {
  AI_OVERLAY_LAYERS_STORAGE_KEY,
  getInitialAiOverlayVisibility,
  hasVisibleAiOverlayLayer,
} from './videoStagePreferences'

describe('VideoStage AI overlay preference', () => {
  it('shows recognition results by default for first-time visitors', () => {
    const storage = { getItem: vi.fn().mockReturnValue(null) }

    expect(getInitialAiOverlayVisibility(storage)).toEqual({
      helmet: true,
      weapon: true,
      pose: true,
      face: true,
      tracking: true,
    })
  })

  it('keeps explicit per-layer user preferences', () => {
    const saved = JSON.stringify({ helmet: true, weapon: false, pose: false, face: true, tracking: false })
    const storage = {
      getItem: (key: string) => key === AI_OVERLAY_LAYERS_STORAGE_KEY ? saved : null,
    }

    expect(getInitialAiOverlayVisibility(storage)).toEqual({
      helmet: true,
      weapon: false,
      pose: false,
      face: true,
      tracking: false,
    })
  })

  it('migrates the old hide-all preference', () => {
    const storage = {
      getItem: (key: string) => key === AI_OVERLAY_LAYERS_STORAGE_KEY ? null : 'false',
    }

    expect(getInitialAiOverlayVisibility(storage)).toEqual({
      helmet: false,
      weapon: false,
      pose: false,
      face: false,
      tracking: false,
    })
  })

  it('reports whether any layer remains visible', () => {
    expect(hasVisibleAiOverlayLayer({ helmet: false, weapon: false, pose: false, face: false, tracking: false })).toBe(false)
    expect(hasVisibleAiOverlayLayer({ helmet: false, weapon: true, pose: false, face: false, tracking: false })).toBe(true)
  })
})
