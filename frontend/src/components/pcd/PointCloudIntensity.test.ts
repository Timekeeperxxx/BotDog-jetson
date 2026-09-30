import { expect, it } from 'vitest'
import { intensityRank } from './PointCloudIntensity'
it('balances skewed intensity quantiles without changing ordering', () => {
  const q = [0, 1, 2, 5, 100]
  expect(q.map(v => intensityRank(v, q))).toEqual([0, .25, .5, .75, 1])
  expect(intensityRank(3.5, q)).toBe(.625)
  expect(intensityRank(-1, q)).toBe(0)
  expect(intensityRank(101, q)).toBe(1)
})
it('keeps ties identical and constant clouds a single color', () => {
  expect(intensityRank(1, [0, 1, 1, 1, 10])).toBe(.5)
  expect(intensityRank(4, [4, 4, 4, 4, 4])).toBe(.5)
})
