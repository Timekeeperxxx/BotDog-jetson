import { describe, expect, it, vi } from 'vitest'
import { PotreeGpuTimer, PotreePerformance } from './PotreePerformance'

function run(control: PotreePerformance, frames: number, delta: number, cost: number, active = true) {
  for (let i = 0; i < frames; i++) control.sample(delta, cost, active)
}

describe('adaptive original detail', () => {
  it('ignores isolated stalls and slow frames unrelated to scene work', () => {
    const c = new PotreePerformance()
    run(c, 120, 16.67, 4); c.sample(120, 100, true); run(c, 120, 16.67, 4)
    run(c, 120, 50, 3)
    expect(c.radius).toBe(0)
  })
  it('responds gradually to sustained load and stops before excessively sparse detail', () => {
    const c = new PotreePerformance()
    run(c, 31, 33.34, 28)
    expect(c.radius).toBe(1)
    run(c, 3000, 33.34, 28)
    expect(c.radius).toBe(24)
  })
  it('recognizes high-refresh frame loss using an observed healthy rhythm', () => {
    const c = new PotreePerformance()
    run(c, 125, 8.34, 2)
    run(c, 61, 16.67, 12)
    expect(c.radius).toBe(1)
  })
  it('requires sustained recovery and continues recovering during following', () => {
    const c = new PotreePerformance()
    run(c, 62, 33.34, 28)
    const reduced = c.radius
    run(c, 60, 16.67, 4)
    expect(c.radius).toBe(reduced)
    run(c, 120, 16.67, 4)
    expect(c.radius).toBe(reduced - .5)
  })
  it('excludes hidden pages and long suspension gaps', () => {
    const c = new PotreePerformance()
    run(c, 120, 50, 45, false); run(c, 20, 1000, 100)
    expect(c.radius).toBe(0)
  })
})

it('reads GPU query results only after availability and disposes pending queries', () => {
  let available = false
  const gl = { getExtension: () => ({ TIME_ELAPSED_EXT: 1, GPU_DISJOINT_EXT: 2 }),
    isContextLost: () => false, getParameter: () => false, getQuery: () => null,
    QUERY_RESULT_AVAILABLE: 3, QUERY_RESULT: 4, CURRENT_QUERY: 5,
    getQueryParameter: vi.fn((_q, param) => param === 3 ? available : 12_000_000),
    createQuery: () => ({}), beginQuery: vi.fn(), endQuery: vi.fn(), deleteQuery: vi.fn() }
  const timer = new PotreeGpuTimer(gl as unknown as WebGL2RenderingContext)
  timer.begin(); timer.end(); timer.begin(); timer.end()
  expect(gl.getQueryParameter.mock.calls.every(([,param]) => param === 3)).toBe(true)
  available = true; timer.begin(); timer.end()
  expect(timer.milliseconds).toBe(12)
  timer.dispose()
  expect(gl.deleteQuery).toHaveBeenCalledTimes(3)
})
