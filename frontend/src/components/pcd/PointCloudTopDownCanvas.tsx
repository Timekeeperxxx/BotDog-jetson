import { useEffect, useMemo, useRef, useState } from 'react'
import type { MouseEvent } from 'react'
import { LocateFixed, ZoomIn, ZoomOut } from 'lucide-react'
import type { NavWaypoint, PcdBounds, PcdSceneLayerRole } from '../../types/pcdMap'
import type { GlobalPath, RobotPose } from '../../types/navState'
import { canvasToMap, mapToCanvas } from '../../utils/topDownCoordinate'

type PointCloudLayer = {
  role: PcdSceneLayerRole
  points: [number, number, number][]
}

type Props = {
  layers?: PointCloudLayer[]
  points?: [number, number, number][]
  viewKey?: string
  bounds: PcdBounds | null
  waypoints: NavWaypoint[]
  robotPose: RobotPose | null
  globalPath: GlobalPath | null
  mode: 'none' | 'waypoint' | 'pose'
  waypointZ: number
  onMouseMapPositionChange: (pos: { x: number; y: number } | null) => void
  onAddWaypoint: (pos: { x: number; y: number; z: number; yaw: number }) => void
  onSetPose: (pos: { x: number; y: number; z: number; yaw: number }) => void
}

const PADDING = 34
const MIN_ZOOM = 0.6
const MAX_ZOOM = 14
const BUTTON_ZOOM_STEP = 1.28
const WHEEL_ZOOM_IN_STEP = 1.18
const WHEEL_ZOOM_OUT_STEP = 0.86
const WAYPOINT_MARKER_RADIUS_PX = 7
const PENDING_MARKER_RADIUS_PX = 8
const ROBOT_MARKER_RADIUS_PX = 9
const WAYPOINT_ARROW_LENGTH_PX = 28
const PENDING_ARROW_LENGTH_PX = 34
const ROBOT_ARROW_LENGTH_PX = 32
const MARKER_OUTLINE_PX = 3

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function getLayerColor(role: PcdSceneLayerRole) {
  if (role === 'ground') return 'rgba(56, 189, 248, 0.60)'
  if (role === 'footprint_fill') return 'rgba(255, 255, 255, 0.78)'
  if (role === 'mapping') return 'rgba(103, 232, 249, 0.42)'
  if (role === 'live') return 'rgba(255, 176, 32, 0.92)'
  return 'rgba(22, 101, 52, 0.85)'
}

function drawScreenMarker(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  fill: string,
  stroke = 'rgba(7, 16, 20, 0.82)',
) {
  ctx.save()
  ctx.fillStyle = fill
  ctx.strokeStyle = stroke
  ctx.lineWidth = MARKER_OUTLINE_PX
  ctx.beginPath()
  ctx.arc(x, y, radius, 0, Math.PI * 2)
  ctx.fill()
  ctx.stroke()
  ctx.restore()
}

function drawTextBadge(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  options: {
    font: string
    fill: string
    background: string
    align?: CanvasTextAlign
  },
) {
  ctx.save()
  ctx.font = options.font
  ctx.textAlign = options.align || 'center'
  ctx.textBaseline = 'middle'
  const metrics = ctx.measureText(text)
  const paddingX = 6
  const paddingY = 3
  const width = metrics.width + paddingX * 2
  const height = 16 + paddingY * 2
  const left = options.align === 'left' ? x : x - width / 2
  const top = y - height / 2

  ctx.fillStyle = options.background
  ctx.beginPath()
  ctx.roundRect(left, top, width, height, 5)
  ctx.fill()

  ctx.fillStyle = options.fill
  ctx.fillText(text, options.align === 'left' ? x + paddingX : x, y)
  ctx.restore()
}

export function PointCloudTopDownCanvas({
  layers,
  points,
  viewKey = 'default',
  bounds,
  waypoints,
  robotPose,
  globalPath,
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
  const staticCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const staticCacheRef = useRef<{
    bounds: PcdBounds | null
    layers: PointCloudLayer[]
    totalPointCount: number
    width: number
    height: number
    ratio: number
  } | null>(null)
  const [pendingWaypoint, setPendingWaypoint] = useState<{
    x: number
    y: number
    z: number
    yaw: number
  } | null>(null)
  const [view, setView] = useState({ zoom: 1, panX: 0, panY: 0 })
  const [isPanning, setIsPanning] = useState(false)

  const normalizedLayers: PointCloudLayer[] = useMemo(
    () => (
      layers?.length
        ? layers
        : points && points.length > 0
          ? [{ role: 'ground', points }]
          : []
    ),
    [layers, points],
  )

  const totalPointCount = useMemo(
    () => normalizedLayers.reduce((sum, layer) => sum + layer.points.length, 0),
    [normalizedLayers],
  )

  useEffect(() => {
    const animationId = window.requestAnimationFrame(() => {
      setView({ zoom: 1, panX: 0, panY: 0 })
    })
    return () => window.cancelAnimationFrame(animationId)
  }, [viewKey])

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
      boundsValue: PcdBounds,
      width: number,
      height: number,
      lengthPx: number,
      color: string,
      lineWidth: number,
    ) => {
      const originBase = mapToCanvas(originMapX, originMapY, boundsValue, width, height, PADDING)
      const tipBase = mapToCanvas(
        originMapX + Math.cos(yaw),
        originMapY + Math.sin(yaw),
        boundsValue,
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

    const drawViewportBackground = (
      ctx: CanvasRenderingContext2D,
      width: number,
      height: number,
    ) => {
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
    }

    const drawStaticMapLayer = (
      ctx: CanvasRenderingContext2D,
      width: number,
      height: number,
    ) => {
      if (!bounds || totalPointCount === 0) return

      normalizedLayers.forEach((layer) => {
        if (layer.points.length === 0) return
        const stride = Math.max(1, Math.floor(layer.points.length / 45000))
        ctx.fillStyle = getLayerColor(layer.role)
        for (let index = 0; index < layer.points.length; index += stride) {
          const point = layer.points[index]
          const pos = mapToCanvas(point[0], point[1], bounds, width, height, PADDING)
          ctx.fillRect(pos.x, pos.y, 1.4, 1.4)
        }
      })

      ctx.strokeStyle = 'rgba(59, 130, 246, 0.75)'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(PADDING, PADDING)
      ctx.lineTo(width - PADDING, PADDING)
      ctx.lineTo(width - PADDING, height - PADDING)
      ctx.lineTo(PADDING, height - PADDING)
      ctx.closePath()
      ctx.stroke()

      ctx.strokeStyle = 'rgba(248, 113, 113, 0.85)'
      ctx.beginPath()
      const x0 = mapToCanvas(bounds.min_x, 0, bounds, width, height, PADDING)
      const x1 = mapToCanvas(bounds.max_x, 0, bounds, width, height, PADDING)
      ctx.moveTo(x0.x, x0.y)
      ctx.lineTo(x1.x, x1.y)
      ctx.stroke()

      ctx.strokeStyle = 'rgba(34, 197, 94, 0.85)'
      ctx.beginPath()
      const y0 = mapToCanvas(0, bounds.min_y, bounds, width, height, PADDING)
      const y1 = mapToCanvas(0, bounds.max_y, bounds, width, height, PADDING)
      ctx.moveTo(y0.x, y0.y)
      ctx.lineTo(y1.x, y1.y)
      ctx.stroke()
    }

    const drawDynamicLayer = (
      ctx: CanvasRenderingContext2D,
      width: number,
      height: number,
    ) => {
      if (!bounds || totalPointCount === 0) return

      if (globalPath && globalPath.frame_id === 'map' && globalPath.points.length > 1) {
        const pathColor = '#facc15'
        ctx.save()
        ctx.strokeStyle = pathColor
        ctx.fillStyle = pathColor
        ctx.lineWidth = 2
        ctx.lineJoin = 'round'
        ctx.lineCap = 'round'
        ctx.beginPath()

        globalPath.points.forEach((point, index) => {
          const basePos = mapToCanvas(point.x, point.y, bounds, width, height, PADDING)
          const pos = applyView(basePos.x, basePos.y, width, height)
          if (index === 0) {
            ctx.moveTo(pos.x, pos.y)
          } else {
            ctx.lineTo(pos.x, pos.y)
          }
        })

        ctx.stroke()

        globalPath.points.forEach((point) => {
          const basePos = mapToCanvas(point.x, point.y, bounds, width, height, PADDING)
          const pos = applyView(basePos.x, basePos.y, width, height)
          ctx.beginPath()
          ctx.arc(pos.x, pos.y, 1.7, 0, Math.PI * 2)
          ctx.fill()
        })
        ctx.restore()
      }

      waypoints.forEach((waypoint, index) => {
        const basePos = mapToCanvas(waypoint.x, waypoint.y, bounds, width, height, PADDING)
        const pos = applyView(basePos.x, basePos.y, width, height)
        drawScreenMarker(ctx, pos.x, pos.y, WAYPOINT_MARKER_RADIUS_PX, '#f59e0b')
        ctx.fillStyle = '#111827'
        ctx.font = 'bold 10px system-ui'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(String(index + 1), pos.x, pos.y)

        drawYawArrow(ctx, waypoint.x, waypoint.y, waypoint.yaw, bounds, width, height, WAYPOINT_ARROW_LENGTH_PX, '#fbbf24', 2)
      })

      if (pendingWaypoint) {
        const basePos = mapToCanvas(pendingWaypoint.x, pendingWaypoint.y, bounds, width, height, PADDING)
        const pos = applyView(basePos.x, basePos.y, width, height)

        ctx.save()
        drawScreenMarker(ctx, pos.x, pos.y, PENDING_MARKER_RADIUS_PX, '#22c55e')
        drawYawArrow(ctx, pendingWaypoint.x, pendingWaypoint.y, pendingWaypoint.yaw, bounds, width, height, PENDING_ARROW_LENGTH_PX, '#86efac', 3)
        ctx.restore()
      }

      if (robotPose) {
        const basePos = mapToCanvas(robotPose.x, robotPose.y, bounds, width, height, PADDING)
        const pos = applyView(basePos.x, basePos.y, width, height)
        const robotColor = robotPose.frame_id === 'map' ? '#f97316' : '#fb7185'

        ctx.save()
        drawScreenMarker(
          ctx,
          pos.x,
          pos.y,
          ROBOT_MARKER_RADIUS_PX,
          robotPose.frame_id === 'map' ? '#ea580c' : '#dc2626',
        )
        drawYawArrow(ctx, robotPose.x, robotPose.y, robotPose.yaw, bounds, width, height, ROBOT_ARROW_LENGTH_PX, robotColor, 3)
        drawTextBadge(ctx, 'BOT', pos.x + 10, pos.y - 14, {
          font: 'bold 11px system-ui',
          fill: '#f8fafc',
          background: 'rgba(7, 16, 20, 0.82)',
          align: 'left',
        })
        ctx.restore()
      }
    }

    const draw = () => {
      const rect = host.getBoundingClientRect()
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      const width = rect.width
      const height = rect.height
      const physicalWidth = Math.max(1, Math.floor(width * ratio))
      const physicalHeight = Math.max(1, Math.floor(height * ratio))

      if (canvas.width !== physicalWidth || canvas.height !== physicalHeight) {
        canvas.width = physicalWidth
        canvas.height = physicalHeight
      }
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`

      if (!staticCanvasRef.current) {
        staticCanvasRef.current = document.createElement('canvas')
      }
      const staticCanvas = staticCanvasRef.current
      const staticCtx = staticCanvas.getContext('2d')
      const ctx = canvas.getContext('2d')
      if (!staticCtx || !ctx) return

      const cache = staticCacheRef.current
      const staticCacheValid = Boolean(
        cache &&
        cache.bounds === bounds &&
        cache.layers === normalizedLayers &&
        cache.totalPointCount === totalPointCount &&
        cache.width === width &&
        cache.height === height &&
        cache.ratio === ratio,
      )

      if (!staticCacheValid) {
        if (staticCanvas.width !== physicalWidth || staticCanvas.height !== physicalHeight) {
          staticCanvas.width = physicalWidth
          staticCanvas.height = physicalHeight
        }
        staticCtx.setTransform(1, 0, 0, 1, 0, 0)
        staticCtx.clearRect(0, 0, physicalWidth, physicalHeight)
        staticCtx.setTransform(ratio, 0, 0, ratio, 0, 0)
        drawStaticMapLayer(staticCtx, width, height)
        staticCacheRef.current = {
          bounds,
          layers: normalizedLayers,
          totalPointCount,
          width,
          height,
          ratio,
        }
      }

      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
      drawViewportBackground(ctx, width, height)
      if (!bounds || totalPointCount === 0) {
        ctx.fillStyle = 'rgba(226, 232, 240, 0.55)'
        ctx.font = '13px system-ui'
        ctx.fillText('等待 XY 投影数据', PADDING, PADDING + 22)
        return
      }

      ctx.save()
      ctx.translate(width / 2 + view.panX, height / 2 + view.panY)
      ctx.scale(view.zoom, view.zoom)
      ctx.translate(-width / 2, -height / 2)
      ctx.drawImage(staticCanvas, 0, 0, width, height)
      ctx.restore()
      drawDynamicLayer(ctx, width, height)
    }

    const resizeObserver = new ResizeObserver(draw)
    resizeObserver.observe(host)
    draw()

    return () => resizeObserver.disconnect()
  }, [bounds, globalPath, normalizedLayers, pendingWaypoint, robotPose, totalPointCount, view, waypoints])

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
          onClick={() => setView((current) => ({ ...current, zoom: clamp(current.zoom * BUTTON_ZOOM_STEP, MIN_ZOOM, MAX_ZOOM) }))}
          title="放大"
        >
          <ZoomIn size={15} />
        </button>
        <button
          className="pcd-icon-button"
          onClick={() => setView((current) => ({ ...current, zoom: clamp(current.zoom / BUTTON_ZOOM_STEP, MIN_ZOOM, MAX_ZOOM) }))}
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
              view.zoom * (event.deltaY < 0 ? WHEEL_ZOOM_IN_STEP : WHEEL_ZOOM_OUT_STEP),
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
                z: pendingWaypoint.z,
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
