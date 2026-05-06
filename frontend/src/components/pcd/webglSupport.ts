export function detectWebGLSupport(): boolean {
  if (typeof document === 'undefined') return false

  const canvas = document.createElement('canvas')
  const contextOptions = { failIfMajorPerformanceCaveat: true } as WebGLContextAttributes

  try {
    if (canvas.getContext('webgl2', contextOptions)) return true
  } catch {
    // ignore
  }

  try {
    if (canvas.getContext('webgl', contextOptions)) return true
  } catch {
    // ignore
  }

  return false
}
