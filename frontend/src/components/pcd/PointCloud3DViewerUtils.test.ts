import { describe, expect, it } from 'vitest'
import {
  SCAN_BODY_CYLINDER_CENTER_Z_OFFSET,
  SCAN_BODY_CYLINDER_HEIGHT,
  SCAN_BODY_CYLINDER_OFFSETS,
  SCAN_BODY_CYLINDER_RADIUS,
  WAYPOINT_LABEL_SCREEN_WIDTH_PX,
} from './PointCloud3DViewerUtils'

describe('B2 SCAN collision-body overlay', () => {
  it('matches the Navigation double-cylinder footprint', () => {
    expect(SCAN_BODY_CYLINDER_RADIUS).toBe(0.36)
    expect(SCAN_BODY_CYLINDER_OFFSETS).toEqual([0, -0.56])
    expect(SCAN_BODY_CYLINDER_HEIGHT).toBe(0.43)
    expect(SCAN_BODY_CYLINDER_CENTER_Z_OFFSET + SCAN_BODY_CYLINDER_HEIGHT / 2).toBeCloseTo(0.10)
    expect(SCAN_BODY_CYLINDER_CENTER_Z_OFFSET - SCAN_BODY_CYLINDER_HEIGHT / 2).toBeCloseTo(-0.33)
  })

  it('keeps waypoint labels legible at normal zoom', () => {
    expect(WAYPOINT_LABEL_SCREEN_WIDTH_PX).toBeGreaterThanOrEqual(100)
  })
})
