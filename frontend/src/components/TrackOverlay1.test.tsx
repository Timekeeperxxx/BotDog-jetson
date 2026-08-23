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

  it('hides weapon boxes when the weapon layer is disabled', () => {
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

    render(
      <div>
        <TrackOverlay
          data={data}
          videoRef={{ current: video }}
          visibility={{ helmet: true, weapon: false, pose: true, face: true, tracking: false }}
        />
      </div>,
    )

    expect(fillText.mock.calls.some(([text]) => String(text).includes('枪械'))).toBe(false)
    expect(context.strokeRect).not.toHaveBeenCalled()
  })

  it('hides face identity text without hiding the safety person box', () => {
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

    render(
      <div>
        <TrackOverlay
          data={data}
          videoRef={{ current: video }}
          visibility={{ helmet: true, weapon: true, pose: true, face: false, tracking: false }}
        />
      </div>,
    )

    expect(context.strokeRect).toHaveBeenCalled()
    expect(fillText.mock.calls.some(([text]) => String(text).includes('测试人员A'))).toBe(false)
  })

  it('draws the head result inside the head bounding box', () => {
    const fillText = vi.fn()
    const fillRect = vi.fn()
    const context = {
      clearRect: vi.fn(), save: vi.fn(), restore: vi.fn(), setLineDash: vi.fn(),
      beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
      fillRect, strokeRect: vi.fn(), fillText, measureText: (text: string) => ({ width: text.length * 6 }),
      arc: vi.fn(), fill: vi.fn(), closePath: vi.fn(),
      fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', globalCompositeOperation: 'source-over',
    }
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 640, height: 360, top: 0, left: 0, right: 640, bottom: 360, x: 0, y: 0, toJSON: () => ({}) })
    const video = document.createElement('video')
    const data: TrackOverlayData = {
      detections: [{ bbox: [100, 50, 180, 120], conf: 0.91, class_name: 'head' }],
      persons: [], active_bbox: null, command: null, reason: '', state: 'IDLE',
      frame_w: 640, frame_h: 360, deadband_px: 80, anchor_y_stop_ratio: 0.2, forward_area_ratio: 0.15,
    }

    render(
      <div>
        <TrackOverlay
          data={data}
          videoRef={{ current: video }}
          visibility={{ helmet: true, weapon: true, pose: true, face: true, tracking: false }}
        />
      </div>,
    )

    expect(fillText.mock.calls.some(([text]) => String(text).includes('head 91%'))).toBe(true)
    expect(fillRect).toHaveBeenCalledWith(100, 50, expect.any(Number), 16)
    expect(fillRect.mock.calls.every(([x, y, width, height]) => (
      x >= 100 && y >= 50 && x + width <= 180 && y + height <= 120
    ))).toBe(true)
  })

  it('merges a matching pose result into the person box without drawing a second box', () => {
    const fillText = vi.fn()
    const fillRect = vi.fn()
    const strokeRect = vi.fn()
    const context = {
      clearRect: vi.fn(), save: vi.fn(), restore: vi.fn(), setLineDash: vi.fn(),
      beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
      fillRect, strokeRect, fillText, measureText: (text: string) => ({ width: text.length * 6 }),
      arc: vi.fn(), fill: vi.fn(), closePath: vi.fn(),
      fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', globalCompositeOperation: 'source-over',
    }
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 640, height: 360, top: 0, left: 0, right: 640, bottom: 360, x: 0, y: 0, toJSON: () => ({}) })
    const video = document.createElement('video')
    const data: TrackOverlayData = {
      detections: [{
        bbox: [100, 50, 300, 340], conf: 0.94, class_name: 'person', track_id: 8,
        face_status: 'recognized', display_name: '测试人员A', is_stranger: false,
      }],
      poses: [{
        bbox: [105, 55, 295, 338], confidence: 0.92, track_id: 77,
        posture: 'crouching', posture_confidence: 0.88, inside_zone: false,
        dwell_seconds: 0, keypoints: Array.from({ length: 17 }, () => [0, 0, 0]),
      }],
      persons: [], active_bbox: null, command: null, reason: '', state: 'IDLE',
      frame_w: 640, frame_h: 360, deadband_px: 80, anchor_y_stop_ratio: 0.2, forward_area_ratio: 0.15,
    }

    render(
      <div>
        <TrackOverlay
          data={data}
          videoRef={{ current: video }}
          visibility={{ helmet: true, weapon: true, pose: true, face: true, tracking: false }}
        />
      </div>,
    )

    expect(fillText.mock.calls.some(([text]) => String(text).includes('姿态：蹲伏 88%'))).toBe(true)
    expect(strokeRect).toHaveBeenCalledTimes(1)
    expect(fillRect.mock.calls.every(([x, y, width, height]) => (
      x >= 100 && y >= 50 && x + width <= 300 && y + height <= 340
    ))).toBe(true)
  })
})
