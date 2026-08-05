import { describe, expect, it, vi } from 'vitest'
import { getInitialAiOverlayVisibility } from './videoStagePreferences'

describe('VideoStage AI overlay preference', () => {
  it('shows recognition results by default for first-time visitors', () => {
    const storage = { getItem: vi.fn().mockReturnValue(null) }

    expect(getInitialAiOverlayVisibility(storage)).toBe(true)
  })

  it('keeps an explicit user preference', () => {
    expect(getInitialAiOverlayVisibility({ getItem: () => 'false' })).toBe(false)
    expect(getInitialAiOverlayVisibility({ getItem: () => 'true' })).toBe(true)
  })
})
