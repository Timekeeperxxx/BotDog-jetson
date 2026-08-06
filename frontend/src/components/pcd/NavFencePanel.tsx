import { Eye, EyeOff, Trash2 } from 'lucide-react'
import type { NavFence } from '../../types/pcdMap'

type Props = {
  fences: NavFence[]
  visible: boolean
  canOperate: boolean
  onToggleVisible: () => void
  onToggleEnabled: (fenceId: string, enabled: boolean) => void
  onDelete: (fenceId: string) => void
}

export function NavFencePanel({
  fences,
  visible,
  canOperate,
  onToggleVisible,
  onToggleEnabled,
  onDelete,
}: Props) {
  return (
    <section className="pcd-panel pcd-waypoint-panel">
      <div className="pcd-panel-heading">
        <div>
          <h2>两点式围栏</h2>
          <p>{fences.length} 条场景围栏</p>
        </div>
        <button className="pcd-icon-button" type="button" onClick={onToggleVisible} title={visible ? '隐藏围栏' : '显示围栏'}>
          {visible ? <Eye size={15} /> : <EyeOff size={15} />}
        </button>
      </div>
      <div className="pcd-waypoint-list">
        {fences.length === 0 ? (
          <div className="pcd-empty">点击“添加围栏”，在地面依次选择起点和终点</div>
        ) : fences.map((fence, index) => (
          <div className="pcd-waypoint-item" key={fence.id}>
            <div>
              <strong>{`围栏 ${index + 1}`}</strong>
              <small>
                ({fence.start.x.toFixed(2)}, {fence.start.y.toFixed(2)}) → ({fence.end.x.toFixed(2)}, {fence.end.y.toFixed(2)})
              </small>
            </div>
            <div className="pcd-waypoint-actions">
              <button
                type="button"
                className={fence.enabled ? 'pcd-secondary-button is-active' : 'pcd-secondary-button'}
                onClick={() => onToggleEnabled(fence.id, !fence.enabled)}
                disabled={!canOperate}
              >
                {fence.enabled ? '已启用' : '已禁用'}
              </button>
              <button
                type="button"
                className="pcd-icon-button"
                onClick={() => onDelete(fence.id)}
                disabled={!canOperate}
                title="删除围栏"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
