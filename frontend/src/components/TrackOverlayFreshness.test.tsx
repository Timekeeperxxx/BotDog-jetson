import { act, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TrackOverlay, type TrackOverlayData } from './TrackOverlay1'

function setup() {
  const context = {
    clearRect: vi.fn(), save: vi.fn(), restore: vi.fn(), setLineDash: vi.fn(),
    beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
    fillRect: vi.fn(), strokeRect: vi.fn(), fillText: vi.fn(),
    measureText: (text: string) => ({ width: text.length * 6 }),
    arc: vi.fn(), fill: vi.fn(), closePath: vi.fn(),
  }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 640, height: 360 } as DOMRect)
  const data: TrackOverlayData = {
    detections: [], persons: [{ bbox: [10, 10, 100, 300], conf: .9 }],
    active_bbox: null, command: null, reason: '', state: 'IDLE',
    frame_w: 640, frame_h: 360, deadband_px: 0, anchor_y_stop_ratio: 0,
    forward_area_ratio: 0,
  }
  const draw = () => render(<div><TrackOverlay data={data} videoRef={{ current: document.createElement('video') }} visibility={{ helmet: true, face: true, pose: true, weapon: true, tracking: false }} /></div>)
  return { context, data, draw }
}

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

describe('overlay freshness', () => {
  it('does not resurrect tracking persons when the current detections are empty', () => {
    const { context, draw } = setup()
    draw()
    expect(context.strokeRect).not.toHaveBeenCalled()
  })
  it('clears the last box when messages stop arriving', () => {
    vi.useFakeTimers()
    const now = vi.spyOn(performance, 'now').mockReturnValue(1000)
    const { context, data, draw } = setup()
    data.detections = data.persons
    data.received_at_ms = 1000
    draw()
    expect(context.strokeRect).toHaveBeenCalled()
    context.strokeRect.mockClear()
    context.clearRect.mockClear()
    now.mockReturnValue(1800)
    act(() => vi.advanceTimersByTime(800))
    expect(context.clearRect).toHaveBeenCalled()
    expect(context.strokeRect).not.toHaveBeenCalled()
  })
})
