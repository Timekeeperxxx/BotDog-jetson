import { Loader2, ScanLine, ShieldCheck } from 'lucide-react'
import type { FenceDetectionState, FenceDetectionStatus } from '../../types/fenceDetection'

const STATE_LABELS: Record<FenceDetectionState, string> = {
  disabled: '未开启',
  finding: '正在查找围栏',
  gimbal_moving: '云台转动中',
  detecting: '云台已对准围栏',
  tracking: '已开启 · 跟踪联动中',
  not_found: '未找到围栏',
  out_of_range: '围栏超出范围',
  localization_unavailable: '定位不可用',
  calibration_unavailable: '标定不可用',
}

type Props = {
  adding: boolean
  canAdd: boolean
  canOperate: boolean
  status: FenceDetectionStatus | null
  loading: boolean
  error: string | null
  onToggleAdd: () => void
  onSetDetectionEnabled: (enabled: boolean) => void
}

export function NavFenceControls({
  adding,
  canAdd,
  canOperate,
  status,
  loading,
  error,
  onToggleAdd,
  onSetDetectionEnabled,
}: Props) {
  const enabled = status?.enabled ?? false
  const showStatus = enabled || Boolean(error)

  return (
    <div className="pcd-fence-control-cluster">
      {showStatus ? (
        <div className="pcd-fence-status-popover" role="status">
          <strong>{error ?? (status ? (enabled ? '动作检测已开启' : '未开启') : '读取状态中')}</strong>
          {!error && status ? <span>观察状态 {STATE_LABELS[status.state]}</span> : null}
          {!error && status && status.state !== 'tracking' ? (
            <div>
              <span>观察围栏 {status.target_fence_id ?? '--'}</span>
              <span>机器人至围栏 {status.distance_m == null ? '--' : `${status.distance_m.toFixed(2)} m`}</span>
            </div>
          ) : null}
          {!error && status?.detail ? <small>{status.detail}</small> : null}
        </div>
      ) : null}
      <button
        type="button"
        className={`pcd-tool-button ${adding ? 'is-active' : ''}`}
        disabled={!canOperate || !canAdd}
        onClick={onToggleAdd}
        title={!canAdd ? '请先选择可导航场景并等待 3D 地图加载' : undefined}
      >
        <ScanLine size={15} />
        <span>{adding ? '退出围栏标记' : '添加围栏'}</span>
      </button>
      <button
        type="button"
        className={`pcd-tool-button ${enabled ? 'is-active' : ''}`}
        disabled={!canOperate || loading || status === null}
        aria-busy={loading}
        onClick={() => onSetDetectionEnabled(!enabled)}
      >
        {loading ? <Loader2 size={15} className="pcd-spin" /> : <ShieldCheck size={15} />}
        <span>{enabled ? '关闭围栏检测' : '开启围栏检测'}</span>
      </button>
    </div>
  )
}
