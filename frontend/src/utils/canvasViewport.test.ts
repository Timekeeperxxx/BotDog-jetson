import { afterEach, describe, expect, it, vi } from 'vitest'
import { CANVAS_PIXEL_BUDGET, getCanvasPixelRatio, observeCanvasViewport } from './canvasViewport'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('canvas display resolution', () => {
  it.each([0.8, 1, 1.25, 1.5, 2])('uses device scale %s for an ordinary viewport', (ratio) => {
    expect(getCanvasPixelRatio(1000, 600, ratio)).toBe(ratio)
  })

  it('caps density and total backing pixels, including large 4K viewports', () => {
    expect(getCanvasPixelRatio(1000, 600, 3)).toBe(2)
    for (const [width, height] of [[1920, 1080], [3840, 2160], [7680, 4320]]) {
      const ratio = getCanvasPixelRatio(width, height, 2)
      expect(Math.floor(width * ratio) * Math.floor(height * ratio)).toBeLessThanOrEqual(CANVAS_PIXEL_BUDGET)
    }
    expect(getCanvasPixelRatio(0, 0, Number.NaN)).toBe(1)
  })

  it('responds to repeated density changes without layout changes and cleans up all listeners', () => {
    const queries: (EventTarget & { media: string })[] = []
    const disconnect = vi.fn()
    let resizeElement: () => void = () => {}
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resizeElement = callback }
      observe() {}
      disconnect = disconnect
    })
    vi.stubGlobal('matchMedia', (media: string) => {
      const query = Object.assign(new EventTarget(), { media })
      queries.push(query)
      return query
    })
    vi.spyOn(window, 'devicePixelRatio', 'get').mockReturnValue(1)
    const update = vi.fn()
    const stop = observeCanvasViewport(document.createElement('div'), update)
    expect(update).toHaveBeenCalledTimes(1)
    expect(queries[0].media).toBe('(resolution: 1dppx)')

    vi.spyOn(window, 'devicePixelRatio', 'get').mockReturnValue(1.5)
    queries[0].dispatchEvent(new Event('change'))
    expect(update).toHaveBeenCalledTimes(2)
    expect(queries[1].media).toBe('(resolution: 1.5dppx)')
    queries[0].dispatchEvent(new Event('change'))
    expect(update).toHaveBeenCalledTimes(2)
    queries[1].dispatchEvent(new Event('change'))
    resizeElement()
    window.dispatchEvent(new Event('resize'))
    expect(update).toHaveBeenCalledTimes(5)

    stop()
    queries.at(-1)!.dispatchEvent(new Event('change'))
    window.dispatchEvent(new Event('resize'))
    expect(update).toHaveBeenCalledTimes(5)
    expect(disconnect).toHaveBeenCalledOnce()
    vi.unstubAllGlobals()
  })
})
