import { useEffect, useRef, useState } from 'react'
import type { MouseEvent } from 'react'
import { LocateFixed, ZoomIn, ZoomOut } from 'lucide-react'
import type { NavWaypoint, PcdBounds } from '../../types/pcdMap'
import type { RobotPose } from '../../types/navState'
import { canvasToMap, mapToCanvas } from '../../utils/topDownCoordinate'

type Props = {
  points: [number, number, number][]
  bounds: PcdBounds | null
  waypoints: NavWaypoint[]
  robotPose: RobotPose | null
  mode: 'none' | 'waypoint' | 'pose'
  waypointZ: number
  onMouseMapPositionChange: (pos: { x: number; y: number } | null) => void
  onAddWaypoint: (pos: { x: number; y: number; z: number; yaw: number }) => void
  onSetPose: (pos: { x: number; y: number; yaw: number }) => void
}

const PADDING = 34
const MIN_ZOOM = 0.6
const MAX_ZOOM = 5

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

export function PointCloudTopDownCanvas({
  points,
  bounds,
  waypoints,
  robotPose,
  mode,
  waypointZ,
  onMouseMapPositionChange,
  onAddWaypoint,
  onSetPose,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const hostRef = useRef<HTMLDivElement | null>(null)
  const panStartRef = useRef<{
    pointerX: number
    pointerY: number
    panX: number
    panY: number
  } | null>(null)
  const [pendingWaypoint, setPendingWaypoint] = useState<{
    x: number
    y: number
    z: number
    yaw: number
  } | null>(null)
  const [view, setView] = useState({ zoom: 1, panX: 0, panY: 0 })
  const [isPanning, setIsPanning] = useState(false)

  useEffect(() => {
    setView({ zoom: 1, panX: 0, panY: 0 })
  }, [bounds, points.length])

  useEffect(() => {
    const canvas = canvasRef.current
    const host = hostRef.current
    if (!canvas || !host) return

    const applyView = (x: number, y: number, width: number, height: number) => {
      const centerX = width / 2
      const centerY = height / 2
      return {
        x: (x - centerX) * view.zoom + centerX + view.panX,
        y: (y - centerY) * view.zoom + centerY + view.panY,
      }
    }

    const drawYawArrow = (
      ctx: CanvasRenderingContext2D,
      originMapX: number,
      originMapY: number,
      yaw: number,
      bounds: PcdBounds,
      width: number,
      height: number,
      lengthPx: number,
      color: string,
      lineWidth: number,
    ) => {
      const originBase = mapToCanvas(originMapX, originMapY, bounds, width, height, PADDING)
      const tipBase = mapToCanvas(
        originMapX + Math.cos(yaw),
        originMapY + Math.sin(yaw),
        bounds,
        width,
        height,
        PADDING,
      )
      const origin = applyView(originBase.x, originBase.y, width, height)
      const tipDirection = {
        x: tipBase.x - originBase.x,
        y: tipBase.y - originBase.y,
      }
      const directionLength = Math.hypot(tipDirection.x, tipDirection.y) || 1
      const unit = {
        x: tipDirection.x / directionLength,
        y: tipDirection.y / directionLength,
      }
      const tip = {
        x: origin.x + unit.x * lengthPx,
        y: origin.y + unit.y * lengthPx,
      }
      const headLength = 10
      const headAngle = Math.atan2(unit.y, unit.x)

      ctx.strokeStyle = color
      ctx.fillStyle = color
      ctx.lineWidth = lineWidth
      ctx.beginPath()
      ctx.moveTo(origin.x, origin.y)
      ctx.lineTo(tip.x, tip.y)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(tip.x, tip.y)
      ctx.lineTo(
        tip.x - headLength * Math.cos(headAngle - Math.PI / 6),
        tip.y - headLength * Math.sin(headAngle - Math.PI / 6),
      )
      ctx.lineTo(
        tip.x - headLength * Math.cos(headAngle + Math.PI / 6),
        tip.y - headLength * Math.sin(headAngle + Math.PI / 6),
      )
      ctx.closePath()
      ctx.fill()
    }

    const draw = () => {
      const rect = host.getBoundingClientRect()
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.max(1, Math.floor(rect.width * ratio))
      canvas.height = Math.max(1, Math.floor(rect.height * ratio))
      canvas.style.width = `${rect.width}px`
      canvas.style.height = `${rect.height}px`

      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
      const width = rect.width
      const height = rect.height

      ctx.fillStyle = '#071013'
      ctx.fillRect(0, 0, width, height)

      ctx.strokeStyle = 'rgba(148, 163, 184, 0.18)'
      ctx.lineWidth = 1
      for (let x = PADDING; x < width - PADDING; x += 40) {
        ctx.beginPath()
        ctx.moveTo(x, PADDING)
        ctx.lineTo(x, height - PADDING)
        ctx.stroke()
      }
      for (let y = PADDING; y < height - PADDING; y += 40) {
        ctx.beginPath()
        ctx.moveTo(PADDING, y)
        ctx.lineTo(width - PADDING, y)
        ctx.stroke()
      }

      if (!bounds || points.length === 0) {
        ctx.fillStyle = 'rgba(226, 232, 240, 0.55)'
        ctx.font = '13px system-ui'
        ctx.fillText('等待 XY 投影数据', PADDING, PADDING + 22)
        return
      }

      ctx.fillStyle = 'rgba(94, 234, 212, 0.58)'
      const stride = Math.max(1, Math.floor(points.length / 45000))
      for (let index = 0; index < points.length; index += stride) {
        const point = points[index]
        const basePos = mapToCanvas(point[0], point[1], bounds, width, height, PADDING)
        const pos = applyView(basePos.x, basePos.y, width, height)
        ctx.fillRect(pos.x, pos.y, 1.4, 1.4)
      }

      ctx.strokeStyle = 'rgba(59, 130, 246, 0.75)'
      ctx.lineWidth = 1.5
      const topLeft = applyView(PADDING, PADDING, width, height)
      const topRight = applyView(width - PADDING, PADDING, width, height)
      const bottomRight = applyView(width - PADDING, height - PADDING, width, height)
      const bottomLeft = applyView(PADDING, height - PADDING, width, height)
      ctx.beginPath()
      ctx.moveTo(topLeft.x, topLeft.y)
      ctx.lineTo(topRight.x, topRight.y)
      ctx.lineTo(bottomRight.x, bottomRight.y)
      ctx.lineTo(bottomLeft.x, bottomLeft.y)
      ctx.closePath()
      ctx.stroke()

      ctx.strokeStyle = 'rgba(248, 113, 113, 0.85)'
      ctx.beginPath()
      const x0Base = mapToCanvas(0, bounds.min_y, bounds, width, height, PADDING)
      const x1Base = mapToCanvas(0, bounds.max_y, bounds, width, height, PADDING)
      const x0 = applyView(x0Base.x, x0Base.y, width, height)
      const x1 = applyView(x1Base.x, x1Base.y, width, height)
      ctx.moveTo(x0.x, x0.y)
      ctx.lineTo(x1.x, x1.y)
      ctx.stroke()

      ctx.strokeStyle = 'rgba(34, 197, 94, 0.85)'
      ctx.beginPath()
      const y0Base = mapToCanvas(bounds.min_x, 0, bounds, width, height, PADDING)
      const y1Base = mapToCanvas(bounds.max_x, 0, bounds, width, height, PADDING)
      const y0 = applyView(y0Base.x, y0Base.y, width, height)
      const y1 = applyView(y1Base.x, y1Base.y, width, height)
      ctx.moveTo(y0.x, y0.y)
      ctx.lineTo(y1.x, y1.y)
      ctx.stroke()

      waypoints.forEach((waypoint, index) => {
        const basePos = mapToCanvas(waypoint.x, waypoint.y, bounds, width, height, PADDING)
        const pos = applyView(basePos.x, basePos.y, width, height)
        ctx.fillStyle = '#f59e0b'
        ctx.beginPath()
        ctx.arc(pos.x, pos.y, 6, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = '#111827'
        ctx.font = 'bold 10px system-ui'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(String(index + 1), pos.x, pos.y)

        drawYawArrow(ctx, waypoint.x, waypoint.y, waypoint.yaw, bounds, width, height, 22, '#fbbf24', 2)
      })

      if (pendingWaypoint) {
        const basePos = mapToCanvas(pendingWaypoint.x, pendingWaypoint.y, bounds, width, height, PADDING)
        const pos = applyView(basePos.x, basePos.y, width, height)

        ctx.save()
        ctx.fillStyle = '#22c55e'
        ctx.beginPath()
        ctx.arc(pos.x, pos.y, 7, 0, Math.PI * 2)
        ctx.fill()
        drawYawArrow(ctx, pendingWaypoint.x, pendingWaypoint.y, pendingWaypoint.yaw, bounds, width, height, 32, '#86efac', 3)
        ctx.restore()
      }

      if (robotPose) {
        const basePos = mapToCanvas(robotPose.x, robotPose.y, bounds, width, height, PADDING)
        const pos = applyView(basePos.x, basePos.y, width, height)
        const robotColor = robotPose.frame_id === 'map' ? '#7dd3fc' : '#fca5a5'

        ctx.save()
        ctx.fillStyle = robotPose.frame_id === 'map' ? '#38bdf8' : '#ef4444'
        ctx.beginPath()
        ctx.arc(pos.x, pos.y, 8, 0, Math.PI * 2)
        ctx.fill()
        drawYawArrow(ctx, robotPose.x, robotPose.y, robotPose.yaw, bounds, width, height, 28, robotColor, 3)

        ctx.font = 'bold 11px system-ui'
        ctx.textAlign = 'left'
        ctx.textBaseline = 'bottom'
        ctx.fillText('BOT', pos.x + 10, pos.y - 10)
        ctx.restore()
      }
    }

    const resizeObserver = new ResizeObserver(draw)
    resizeObserver.observe(host)
    draw()

    return () => resizeObserver.disconnect()
  }, [bounds, pendingWaypoint, points, robotPose, view, waypoints])

  const readMapPosition = (event: MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas || !bounds) return null
    const rect = canvas.getBoundingClientRect()
    const screenX = event.clientX - rect.left
    const screenY = event.clientY - rect.top
    const centerX = rect.width / 2
    const centerY = rect.height / 2
    const baseX = (screenX - centerX - view.panX) / view.zoom + centerX
    const baseY = (screenY - centerY - view.panY) / view.zoom + centerY
    return canvasToMap(baseX, baseY, bounds, rect.width, rect.height, PADDING)
  }

  return (
    <div className="pcd-viewer-shell pcd-topdown-shell">
      <div className="pcd-viewer-label">2D 俯视投影</div>
      <div className="pcd-topdown-toolbar">
        <button
          className="pcd-icon-button"
          onClick={() => setView((current) => ({ ...current, zoom: clamp(current.zoom * 1.18, MIN_ZOOM, MAX_ZOOM) }))}
          title="放大"
        >
          <ZoomIn size={15} />
        </button>
        <button
          className="pcd-icon-button"
          onClick={() => setView((current) => ({ ...current, zoom: clamp(current.zoom / 1.18, MIN_ZOOM, MAX_ZOOM) }))}
          title="缩小"
        >
          <ZoomOut size={15} />
        </button>
        <button
          className="pcd-icon-button"
          onClick={() => setView({ zoom: 1, panX: 0, panY: 0 })}
          title="复位视图"
        >
          <LocateFixed size={15} />
        </button>
      </div>
      <div className="pcd-canvas-host" ref={hostRef}>
        <canvas
          ref={canvasRef}
          className={mode !== 'none' ? 'is-adding' : isPanning ? 'is-panning' : 'is-draggable'}
          onWheel={(event) => {
            if (!bounds) return
            event.preventDefault()
            const canvas = canvasRef.current
            if (!canvas) return
            const rect = canvas.getBoundingClientRect()
            const cursorX = event.clientX - rect.left
            const cursorY = event.clientY - rect.top
            const centerX = rect.width / 2
            const centerY = rect.height / 2
            const nextZoom = clamp(
              view.zoom * (event.deltaY < 0 ? 1.12 : 0.9),
              MIN_ZOOM,
              MAX_ZOOM,
            )
            const baseX = (cursorX - centerX - view.panX) / view.zoom + centerX
            const baseY = (cursorY - centerY - view.panY) / view.zoom + centerY
            setView({
              zoom: nextZoom,
              panX: cursorX - ((baseX - centerX) * nextZoom + centerX),
              panY: cursorY - ((baseY - centerY) * nextZoom + centerY),
            })
          }}
          onMouseDown={(event) => {
            if (mode === 'none') {
              panStartRef.current = {
                pointerX: event.clientX,
                pointerY: event.clientY,
                panX: view.panX,
                panY: view.panY,
              }
              setIsPanning(true)
              return
            }
            const position = readMapPosition(event)
            if (!position) return
            setPendingWaypoint({
              x: position.x,
              y: position.y,
              z: mode === 'waypoint' ? waypointZ : 0,
              yaw: 0,
            })
          }}
          onMouseMove={(event) => {
            const position = readMapPosition(event)
            onMouseMapPositionChange(position)
            if (mode === 'none' && panStartRef.current) {
              const dx = event.clientX - panStartRef.current.pointerX
              const dy = event.clientY - panStartRef.current.pointerY
              setView((current) => {
                const panStart = panStartRef.current
                if (!panStart) return current
                return {
                  ...current,
                  panX: panStart.panX + dx,
                  panY: panStart.panY + dy,
                }
              })
              return
            }
            if (mode === 'none' || !position || !pendingWaypoint) return
            setPendingWaypoint((current) => {
              if (!current) return current
              const dx = position.x - current.x
              const dy = position.y - current.y
              const yaw = Math.abs(dx) < 0.0001 && Math.abs(dy) < 0.0001
                ? current.yaw
                : Math.atan2(dy, dx)
              return { ...current, yaw }
            })
          }}
          onMouseLeave={() => {
            onMouseMapPositionChange(null)
            panStartRef.current = null
            setIsPanning(false)
          }}
          onMouseUp={() => {
            if (mode === 'none') {
              panStartRef.current = null
              setIsPanning(false)
              return
            }
            if (!pendingWaypoint) return
            if (mode === 'waypoint') {
              onAddWaypoint(pendingWaypoint)
            } else {
              onSetPose({
                x: pendingWaypoint.x,
                y: pendingWaypoint.y,
                yaw: pendingWaypoint.yaw,
              })
            }
            setPendingWaypoint(null)
          }}
        />
      </div>
    </div>
  )
}
