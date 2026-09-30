import type { CloudMotion } from './PotreeMotion'
import { cloudLoadConcurrency } from './PotreeMotion'

/** In-flight work only; downloaded point data has no capacity limit. */
export class PotreeLoadRamp {
  private limit = 6
  private lastChange = 0
  private wasStationary = false
  next(mode: CloudMotion, now: number, frameMs: number, workMs: number) {
    if (mode !== 'stationary') {
      this.wasStationary = false
      return cloudLoadConcurrency(mode, frameMs, workMs)
    }
    if (!this.wasStationary) {
      this.limit = 6; this.lastChange = now; this.wasStationary = true
    }
    if (frameMs > 45 || workMs > 16) {
      this.limit = 2; this.lastChange = now
    } else if (now - this.lastChange >= 500) {
      if (frameMs < 24 && workMs < 8) this.limit = Math.min(24, this.limit + 2)
      else if (frameMs > 32 || workMs > 12) this.limit = Math.max(2, this.limit - 2)
      this.lastChange = now
    }
    return this.limit
  }
}

/** Potree's public update admits two nodes per pass. Additional passes use
 * available CPU time, without modifying the dependency's private internals.
 * A pass is indivisible; its observed cost reserves time for the next pass. */
export function refineWithinBudget<T extends { exceededMaxLoadsToGPU: boolean }>(
  update: () => T, budgetMs: number, clock = () => performance.now(),
) {
  const start = clock()
  let result = update()
  let passes = 1
  let passCost = clock() - start
  while (result.exceededMaxLoadsToGPU && passes < 8 && clock() - start + Math.max(.25, passCost) < budgetMs) {
    const before = clock()
    result = update(); passes++
    passCost = Math.max(passCost, clock() - before)
  }
  return result
}
