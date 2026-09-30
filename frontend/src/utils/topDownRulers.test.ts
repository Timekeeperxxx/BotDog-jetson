import { describe, expect, it } from 'vitest'
import { getMapExtents, getTopDownRulers } from './topDownRulers'
import { canvasToMap, getTopDownScale } from './topDownCoordinate'

const bounds = { min_x: -20, max_x: 80, min_y: -10, max_y: 40, min_z: 0, max_z: 1 }

describe('map extents and metric rulers', () => {
  it('computes the full bounding rectangle, including negative coordinates', () => {
    expect(getMapExtents(bounds)).toEqual({ x: 100, y: 50, area: 5000 })
    expect(getMapExtents({ ...bounds, max_x: bounds.min_x })?.area).toBe(0)
    expect(getMapExtents(null)).toBeNull()
    expect(getMapExtents({ ...bounds, max_x: NaN })).toBeNull()
    expect(getMapExtents({ ...bounds, min_y: 100 })).toBeNull()
  })

  it.each([{ zoom: 1, panX: 0, panY: 0 }, { zoom: 3.2, panX: -70, panY: 35 }, { zoom: 0.6, panX: 10, panY: -15 }])(
    'keeps tick labels at their true coordinates after zoom and pan: %j', view => {
      const size = 440, padding = 48
      const rulers = getTopDownRulers(bounds, size, size, padding, view)
      expect(rulers.x.length).toBeGreaterThan(1)
      expect(rulers.y.length).toBeGreaterThan(1)
      for (const axis of ['x', 'y'] as const) {
        for (const tick of rulers[axis]) {
          expect(tick.position).toBeGreaterThanOrEqual(padding - 0.001)
          expect(tick.position).toBeLessThanOrEqual(size - padding + 0.001)
          const base = (tick.position - size / 2 - (axis === 'x' ? view.panY : view.panX)) / view.zoom + size / 2
          const point = canvasToMap(axis === 'y' ? base : 0, axis === 'x' ? base : 0, bounds, size, size, padding)
          expect(point[axis]).toBeCloseTo(tick.value, 7)
          expect(Number(tick.label)).toBeCloseTo(tick.value, 6)
        }
      }
      const [a, b] = rulers.x
      expect(Math.abs(b.position - a.position)).toBeCloseTo((b.value - a.value) * getTopDownScale(bounds, size, size, padding) * view.zoom)
      expect(getMapExtents(bounds)?.area).toBe(5000)
    },
  )

  it('handles small views without producing invalid ruler positions', () => {
    expect(getTopDownRulers(bounds, 50, 50, 48, { zoom: 1, panX: 0, panY: 0 })).toEqual({ x: [], y: [] })
  })
})
