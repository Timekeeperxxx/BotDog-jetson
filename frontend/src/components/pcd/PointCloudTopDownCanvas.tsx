import { useEffect, useRef } from 'react'
import type { MouseEvent } from 'react'
import type { NavWaypoint, PcdBounds } from '../../types/pcdMap'
import type { RobotPose } from '../../types/navState'
import { canvasToMap, mapToCanvas } from '../../utils/topDownCoordinate'

type Props = {
  points: [number, number, number][]
  bounds: PcdBounds | null
  waypoints: NavWaypoint[]
  robotPose: RobotPose | null
  addMode: boolean
  onMouseMapPositionChange: (pos: { x: number; y: number } | null) => void
  onAddWaypoint: (pos: { x: number; y: number }) => void
}

const PADDING = 34

export function PointCloudTopDownCanvas({
  points,
  bounds,
  waypoints,
  robotPose,
  addMode,
  onMouseMapPositionChange,
  onAddWaypoint,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const hostRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const host = hostRef.current
    if (!canvas || !host) return

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
        const pos = mapToCanvas(point[0], point[1], bounds, width, height, PADDING)
        ctx.fillRect(pos.x, pos.y, 1.4, 1.4)
      }

      ctx.strokeStyle = 'rgba(59, 130, 246, 0.75)'
      ctx.lineWidth = 1.5
      ctx.strokeRect(PADDING, PADDING, width - PADDING * 2, height - PADDING * 2)

      ctx.strokeStyle = 'rgba(248, 113, 113, 0.85)'
      ctx.beginPath()
      const x0 = mapToCanvas(0, bounds.min_y, bounds, width, height, PADDING)
      const x1 = mapToCanvas(0, bounds.max_y, bounds, width, height, PADDING)
      ctx.moveTo(x0.x, x0.y)
      ctx.lineTo(x1.x, x1.y)
      ctx.stroke()

      ctx.strokeStyle = 'rgba(34, 197, 94, 0.85)'
      ctx.beginPath()
      const y0 = mapToCanvas(bounds.min_x, 0, bounds, width, height, PADDING)
      const y1 = mapToCanvas(bounds.max_x, 0, bounds, width, height, PADDING)
      ctx.moveTo(y0.x, y0.y)
      ctx.lineTo(y1.x, y1.y)
      ctx.stroke()

      waypoints.forEach((waypoint, index) => {
        const pos = mapToCanvas(waypoint.x, waypoint.y, bounds, width, height, PADDING)
        ctx.fillStyle = '#f59e0b'
        ctx.beginPath()
        ctx.arc(pos.x, pos.y, 6, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = '#111827'
        ctx.font = 'bold 10px system-ui'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(String(index + 1), pos.x, pos.y)
      })

      if (robotPose) {
        const pos = mapToCanvas(robotPose.x, robotPose.y, bounds, width, height, PADDING)
        const arrowLength = 28
        const arrowX = Math.cos(robotPose.yaw) * arrowLength
        const arrowY = -Math.sin(robotPose.yaw) * arrowLength
        const tipX = pos.x + arrowX
        const tipY = pos.y + arrowY
        const headLength = 10
        const headAngle = Math.atan2(arrowY, arrowX)

        ctx.save()
        ctx.fillStyle = robotPose.frame_id === 'map' ? '#38bdf8' : '#ef4444'
        ctx.strokeStyle = robotPose.frame_id === 'map' ? '#7dd3fc' : '#fca5a5'
        ctx.lineWidth = 3
        ctx.beginPath()
        ctx.arc(pos.x, pos.y, 8, 0, Math.PI * 2)
        ctx.fill()
        ctx.beginPath()
        ctx.moveTo(pos.x, pos.y)
        ctx.lineTo(tipX, tipY)
        ctx.stroke()

        ctx.beginPath()
        ctx.moveTo(tipX, tipY)
        ctx.lineTo(
          tipX - headLength * Math.cos(headAngle - Math.PI / 6),
          tipY - headLength * Math.sin(headAngle - Math.PI / 6),
        )
        ctx.lineTo(
          tipX - headLength * Math.cos(headAngle + Math.PI / 6),
          tipY - headLength * Math.sin(headAngle + Math.PI / 6),
        )
        ctx.closePath()
        ctx.fill()

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
  }, [bounds, points, robotPose, waypoints])

  const readMapPosition = (event: MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas || !bounds) return null
    const rect = canvas.getBoundingClientRect()
    const canvasX = event.clientX - rect.left
    const canvasY = event.clientY - rect.top
    return canvasToMap(canvasX, canvasY, bounds, rect.width, rect.height, PADDING)
  }

  return (
    <div className="pcd-viewer-shell pcd-topdown-shell">
      <div className="pcd-viewer-label">2D 俯视投影</div>
      <div className="pcd-canvas-host" ref={hostRef}>
        <canvas
          ref={canvasRef}
          className={addMode ? 'is-adding' : ''}
          onMouseMove={(event) => onMouseMapPositionChange(readMapPosition(event))}
          onMouseLeave={() => onMouseMapPositionChange(null)}
          onClick={(event) => {
            if (!addMode) return
            const position = readMapPosition(event)
            if (position) onAddWaypoint(position)
          }}
        />
      </div>
    </div>
  )
}
