import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TrackOverlay, type TrackOverlayData } from './TrackOverlay1'

describe('TrackOverlay face labels', () => {
  it('draws recognized display name in the person header', () => {
    const fillText = vi.fn()
    const context = {
      clearRect: vi.fn(), save: vi.fn(), restore: vi.fn(), setLineDash: vi.fn(),
      beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
      fillRect: vi.fn(), strokeRect: vi.fn(), fillText, measureText: (text: string) => ({ width: text.length * 6 }),
      arc: vi.fn(), fill: vi.fn(), closePath: vi.fn(),
      fillStyle: '', strokeStyle: '', lineWidth: 1, font: '',
    }
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 640, height: 360, top: 0, left: 0, right: 640, bottom: 360, x: 0, y: 0, toJSON: () => ({}) })
    const video = document.createElement('video')
    const data: TrackOverlayData = {
      detections: [{ bbox: [100, 50, 300, 340], conf: 0.94, class_name: 'person', track_id: 8, face_status: 'recognized', display_name: '测试人员A' }],
      persons: [], active_bbox: null, command: null, reason: '', state: 'IDLE',
      frame_w: 640, frame_h: 360, deadband_px: 80, anchor_y_stop_ratio: 0.2, forward_area_ratio: 0.15,
    }

    render(<div><TrackOverlay data={data} videoRef={{ current: video }} /></div>)

    expect(fillText.mock.calls.some(([text]) => String(text).includes('测试人员A'))).toBe(true)
  })

  it('draws localized weapon labels', () => {
    const fillText = vi.fn()
    const context = {
      clearRect: vi.fn(), save: vi.fn(), restore: vi.fn(), setLineDash: vi.fn(),
      beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
      fillRect: vi.fn(), strokeRect: vi.fn(), fillText, measureText: (text: string) => ({ width: text.length * 6 }),
      arc: vi.fn(), fill: vi.fn(), closePath: vi.fn(),
      fillStyle: '', strokeStyle: '', lineWidth: 1, font: '',
    }
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 640, height: 360, top: 0, left: 0, right: 640, bottom: 360, x: 0, y: 0, toJSON: () => ({}) })
    const video = document.createElement('video')
    const data: TrackOverlayData = {
      detections: [{ bbox: [100, 50, 160, 180], conf: 0.79, class_name: 'guns' }],
      persons: [], active_bbox: null, command: null, reason: '', state: 'IDLE',
      frame_w: 640, frame_h: 360, deadband_px: 80, anchor_y_stop_ratio: 0.2, forward_area_ratio: 0.15,
    }

    render(<div><TrackOverlay data={data} videoRef={{ current: video }} /></div>)

    expect(fillText.mock.calls.some(([text]) => String(text).includes('枪械'))).toBe(true)
  })
})
