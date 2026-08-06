import { Loader2, ScanLine, ShieldCheck } from 'lucide-react'
import type { FenceBehavior, FenceDetectionState, FenceDetectionStatus } from '../../types/fenceDetection'

const STATE_LABELS: Record<FenceDetectionState, string> = {
  disabled: '未开启',
  finding: '正在查找围栏',
  gimbal_moving: '云台转动中',
  detecting: '检测中',
  not_found: '未找到围栏',
  out_of_range: '围栏超出范围',
  localization_unavailable: '定位不可用',
  calibration_unavailable: '标定不可用',
}

const BEHAVIOR_LABELS: Record<FenceBehavior, string> = {
  normal: '正常',
  approaching: '靠近围栏',
  dwelling: '围栏附近停留',
  contact: '接触围栏',
  climbing_suspected: '疑似翻越',
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
          <strong>{error ?? (status ? STATE_LABELS[status.state] : '读取状态中')}</strong>
          {!error && status ? (
            <div>
              <span>目标 {status.target_fence_id ?? '--'}</span>
              <span>距离 {status.distance_m == null ? '--' : `${status.distance_m.toFixed(2)} m`}</span>
              <span>人员 {BEHAVIOR_LABELS[status.behavior]}{status.behavior_track_id == null ? '' : ` #${status.behavior_track_id}`}</span>
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
        disabled={!canOperate || loading}
        onClick={() => onSetDetectionEnabled(!enabled)}
      >
        {loading ? <Loader2 size={15} className="pcd-spin" /> : <ShieldCheck size={15} />}
        <span>{enabled ? '关闭围栏检测' : '开启围栏检测'}</span>
      </button>
    </div>
  )
}
