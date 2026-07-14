import { ChevronDown, ChevronUp } from 'lucide-react'
import type { LocalizationStatus, RobotPose } from '../../types/navState'
import type { PcdSceneMetadata } from '../../types/pcdMap'
import type { LogItem } from './navPageUtils'
import { summarizeLocalizationStatus } from './navPageUtils'

type SceneInfoDrawerProps = {
  open: boolean
  metadata: PcdSceneMetadata | null
  mouseMapPosition: { x: number; y: number } | null
  robotPose: RobotPose | null
  selectedSceneReady: boolean
  selectedSceneNavigable: boolean
  selectedSceneMessage: string | null
  localizationStatus: LocalizationStatus | null
  onToggle: () => void
}

export function SceneInfoDrawer({
  open,
  metadata,
  mouseMapPosition,
  robotPose,
  selectedSceneReady,
  selectedSceneNavigable,
  selectedSceneMessage,
  localizationStatus,
  onToggle,
}: SceneInfoDrawerProps) {
  return (
    <div className="pcd-overlay-stack">
      <section className={`pcd-panel pcd-floating-panel pcd-info-drawer ${open ? 'is-open' : 'is-closed'}`}>
        <button
          className="pcd-info-toggle"
          onClick={onToggle}
          title={open ? '收起场景和位姿信息' : '展开场景和位姿信息'}
        >
          <div>
            <strong>场景信息 / 机器狗坐标</strong>
            <span>{metadata?.name || '未选择场景'}</span>
          </div>
          {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {open ? (
          <div className="pcd-info-drawer-body">
            {metadata ? (
              <div className="pcd-metadata-grid">
                <span>坐标系</span>
                <strong>{metadata.frame_id}</strong>
                <span>点数量</span>
                <strong>{metadata.point_count.toLocaleString()}</strong>
                <span>DATA</span>
                <strong>{metadata.data_type}</strong>
                <span>字段</span>
                <strong>{metadata.fields.join(', ')}</strong>
                <span>鼠标 X/Y</span>
                <strong>
                  {mouseMapPosition
                    ? `${mouseMapPosition.x.toFixed(3)}, ${mouseMapPosition.y.toFixed(3)}`
                    : '-'}
                </strong>
                <span>X / Y</span>
                <strong>{robotPose ? `${robotPose.x.toFixed(3)}, ${robotPose.y.toFixed(3)}` : '-'}</strong>
                <span>Z</span>
                <strong>{robotPose ? robotPose.z.toFixed(3) : '-'}</strong>
                <span>Yaw</span>
                <strong>{robotPose ? `${robotPose.yaw.toFixed(3)} rad` : '-'}</strong>
                <span>Frame</span>
                <strong>{robotPose?.frame_id || '-'}</strong>
                <span>Source</span>
                <strong>{robotPose?.source || '-'}</strong>
                <span>场景状态</span>
                <strong>{selectedSceneReady ? 'ready' : 'incomplete'}</strong>
                <span>可导航</span>
                <strong>{selectedSceneNavigable ? 'yes' : 'no'}</strong>
              </div>
            ) : (
              <div className="pcd-empty">选择场景后显示场景信息和机器狗位姿</div>
            )}
            {selectedSceneMessage ? (
              <div className="pcd-warning">{selectedSceneMessage}</div>
            ) : null}
            {metadata?.bounds ? (
              <div className="pcd-bounds">
                <div>X: {metadata.bounds.min_x.toFixed(3)} / {metadata.bounds.max_x.toFixed(3)}</div>
                <div>Y: {metadata.bounds.min_y.toFixed(3)} / {metadata.bounds.max_y.toFixed(3)}</div>
                <div>Z: {metadata.bounds.min_z.toFixed(3)} / {metadata.bounds.max_z.toFixed(3)}</div>
              </div>
            ) : null}
            {robotPose && robotPose.frame_id !== 'map' ? (
              <div className="pcd-warning">当前位姿不是 map 坐标系：{robotPose.frame_id}</div>
            ) : null}
            {!selectedSceneNavigable ? (
              <div className="pcd-warning">当前场景缺少 ground.pcd，不能用于导航</div>
            ) : null}
            {localizationStatus ? (
              <div
                className={localizationStatus.status === 'ok' ? 'pcd-bounds' : 'pcd-warning'}
                title={localizationStatus.message}
              >
                {summarizeLocalizationStatus(localizationStatus.status, localizationStatus.message)}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  )
}

type Notice = {
  title: string
  message: string
} | null

type NavMessageCenterProps = {
  notice: Notice
  noticeKind: string
  logs: LogItem[]
  expanded: boolean
  onToggleExpanded: () => void
}

export function NavMessageCenter({
  notice,
  noticeKind,
  logs,
  expanded,
  onToggleExpanded,
}: NavMessageCenterProps) {
  const latestLog = logs[0] ?? null

  return (
    <section className={`pcd-message-center is-${noticeKind} ${expanded ? 'is-log-expanded' : ''}`} aria-live="polite">
      <div className="pcd-message-primary" title={notice?.message || undefined}>
        <span className="pcd-message-label">提示中心</span>
        <strong>{notice?.title || '待命'}</strong>
        <span>{notice?.message || '无新的操作提醒。'}</span>
      </div>
      <div className="pcd-message-log">
        <button
          type="button"
          className="pcd-message-log-toggle"
          onClick={onToggleExpanded}
          title={expanded ? '收起导航日志' : '展开导航历史日志'}
          aria-expanded={expanded}
        >
          <span className="pcd-message-label">最近日志</span>
          <span className={latestLog?.level === 'error' ? 'is-error' : ''}>
            {latestLog?.message || '等待操作日志'}
          </span>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        {expanded ? (
          <div className="pcd-message-log-history" role="log" aria-label="导航历史日志">
            {logs.length > 0 ? (
              logs.map((item) => (
                <div key={item.id} className={item.level === 'error' ? 'is-error' : ''}>
                  {item.message}
                </div>
              ))
            ) : (
              <div>暂无历史日志</div>
            )}
          </div>
        ) : null}
      </div>
    </section>
  )
}
