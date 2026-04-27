import { Trash2 } from 'lucide-react'
import type { NavWaypoint } from '../../types/pcdMap'

type Props = {
  waypoints: NavWaypoint[]
  onDelete: (waypointId: string) => void
}

export function NavWaypointPanel({ waypoints, onDelete }: Props) {
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
                  x {point.x.toFixed(3)} · y {point.y.toFixed(3)} · yaw {point.yaw.toFixed(2)}
                </span>
              </div>
              <button
                className="pcd-icon-button danger"
                onClick={() => onDelete(point.id)}
                title="删除导航点"
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))
        )}
      </div>
    </section>
  )
}
