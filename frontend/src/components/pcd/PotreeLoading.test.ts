import { describe, expect, it } from 'vitest'
import { PotreeLoadRamp, refineWithinBudget } from './PotreeLoading'
import { PotreePerformance } from './PotreePerformance'

describe('stationary loading acceleration', () => {
  it('ramps in-flight loading with headroom and backs off under pressure', () => {
    const ramp = new PotreeLoadRamp()
    expect(ramp.next('stationary', 0, 16, 3)).toBe(6)
    expect(ramp.next('stationary', 499, 16, 3)).toBe(6)
    expect(ramp.next('stationary', 500, 16, 3)).toBe(8)
    expect(ramp.next('stationary', 600, 50, 20)).toBe(2)
    expect(ramp.next('following', 700, 16, 3)).toBe(5)
    expect(ramp.next('stationary', 800, 16, 3)).toBe(6)
  })
  it('allows several cheap admission passes but avoids another expensive pass', () => {
    let now = 0, passes = 0
    refineWithinBudget(() => { now += .5; passes++; return { exceededMaxLoadsToGPU: true } }, 3, () => now)
    expect(passes).toBeGreaterThan(2)
    expect(now).toBeLessThanOrEqual(3)
    now = 0; passes = 0
    refineWithinBudget(() => { now += 2; passes++; return { exceededMaxLoadsToGPU: true } }, 3, () => now)
    expect(passes).toBe(1)
  })
  it('does not traverse again when there are no ready nodes or no headroom', () => {
    let passes = 0
    refineWithinBudget(() => { passes++; return { exceededMaxLoadsToGPU: false } }, 4)
    expect(passes).toBe(1)
    refineWithinBudget(() => { passes++; return { exceededMaxLoadsToGPU: true } }, 0)
    expect(passes).toBe(2)
  })
  it('restores detail promptly at rest, while retaining detail under sustained pressure', () => {
    const control = new PotreePerformance()
    control.radius = 10
    for (let i = 0; i < 16; i++) control.sample(16.67, 3, true, true)
    expect(control.radius).toBe(8)
    for (let i = 0; i < 8; i++) control.sample(33.34, 28, true, true)
    expect(control.radius).toBe(8)
  })
})
