import { describe, expect, it } from 'vitest'
import { advanceFenceDraft } from './fenceDraft'

describe('advanceFenceDraft', () => {
  it('creates one fence after two distinct map clicks', () => {
    const first = advanceFenceDraft(null, { x: 1, y: 2, z: 0 })
    expect(first.completed).toBeNull()
    expect(first.start).toEqual({ x: 1, y: 2, z: 0 })

    const second = advanceFenceDraft(first.start, { x: 5, y: 3, z: 0 })
    expect(second.start).toBeNull()
    expect(second.completed).toEqual({
      start: { x: 1, y: 2, z: 0 },
      end: { x: 5, y: 3, z: 0 },
    })
  })

  it('ignores an accidental second click at the same position', () => {
    const start = { x: 1, y: 2, z: 0 }
    expect(advanceFenceDraft(start, { x: 1.005, y: 2, z: 0 })).toEqual({
      start,
      completed: null,
    })
  })
})
