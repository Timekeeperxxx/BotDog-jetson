import { Navigation, Trash2 } from 'lucide-react'
import type { NavWaypoint } from '../../types/pcdMap'

type Props = {
  waypoints: NavWaypoint[]
  navigatingWaypointId: string | null
  onGoTo: (waypointId: string) => void
  onDelete: (waypointId: string) => void
}

export function NavWaypointPanel({ waypoints, navigatingWaypointId, onGoTo, onDelete }: Props) {
  return (
    <section className="pcd-panel pcd-waypoint-panel">
      <div className="pcd-panel-header">
        <div>
          <h2>导航点</h2>
          <p>{waypoints.length} 个 map 坐标点</p>
        </div>
      </div>

      <div className="pcd-waypoint-list">
        {waypoints.length === 0 ? (
          <div className="pcd-empty">在 2D 俯视图中开启标点后点击添加</div>
        ) : (
          waypoints.map((point) => (
            <div className="pcd-waypoint-item" key={point.id}>
              <div>
                <strong>{point.name}</strong>
                <span>
                  x {point.x.toFixed(3)} · y {point.y.toFixed(3)} · z {point.z.toFixed(3)}
                </span>
                <span>
                  yaw {point.yaw.toFixed(3)} rad
                </span>
              </div>
              <div className="pcd-waypoint-actions">
                <button
                  className="pcd-icon-button"
                  onClick={() => onGoTo(point.id)}
                  disabled={navigatingWaypointId === point.id}
                  title="导航到该点"
                >
                  <Navigation size={15} />
                </button>
                <button
                  className="pcd-icon-button danger"
                  onClick={() => onDelete(point.id)}
                  title="删除导航点"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  )
}
