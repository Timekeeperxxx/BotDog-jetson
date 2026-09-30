/** Fixed full-layer quantiles; ties share one midpoint rank at every view/LOD. */
export function intensityRank(value: number, quantiles: number[]) {
  const n = quantiles.length
  if (n < 2 || !Number.isFinite(value)) return .5
  if (value < quantiles[0]) return 0
  if (value > quantiles[n - 1]) return 1
  let lo = 0, hi = n
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (quantiles[mid] < value) lo = mid + 1
    else hi = mid
  }
  const first = lo
  if (quantiles[first] === value) {
    hi = n
    while (lo < hi) {
      const mid = (lo + hi) >>> 1
      if (quantiles[mid] <= value) lo = mid + 1
      else hi = mid
    }
    return (first + lo - 1) / (2 * (n - 1))
  }
  return (first - 1 + (value - quantiles[first - 1]) / (quantiles[first] - quantiles[first - 1])) / (n - 1)
}
