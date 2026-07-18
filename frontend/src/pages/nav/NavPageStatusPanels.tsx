import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleDot,
  Info,
  LoaderCircle,
  ScrollText,
} from 'lucide-react'
import type { LocalizationStatus, RobotPose } from '../../types/navState'
import type { PcdSceneMetadata } from '../../types/pcdMap'
import type { LogItem } from './navPageUtils'
import { summarizeLocalizationStatus } from './navPageUtils'

type SceneInfoDrawerProps = {
  open: boolean
  metadata: PcdSceneMetadata | null
  sceneDisplayPointCount: number | null
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
  sceneDisplayPointCount,
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
                <span>ground 点数</span>
                <strong>{metadata.point_count.toLocaleString()}</strong>
                {sceneDisplayPointCount !== null ? (
                  <>
                    <span>场景点数</span>
                    <strong>{sceneDisplayPointCount.toLocaleString()}</strong>
                  </>
                ) : null}
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
  const errorCount = logs.filter((item) => item.level === 'error').length
  const noticeLabel = noticeKind === 'error'
    ? '异常'
    : noticeKind === 'ready' || noticeKind === 'localized'
      ? '完成'
      : noticeKind === 'waiting' || noticeKind === 'restarting'
        ? '进行中'
        : noticeKind === 'info'
          ? '消息'
          : '状态'
  const noticeIcon = noticeKind === 'error'
    ? <AlertTriangle size={19} />
    : noticeKind === 'ready' || noticeKind === 'localized'
      ? <CheckCircle2 size={19} />
      : noticeKind === 'waiting' || noticeKind === 'restarting'
        ? <LoaderCircle size={19} className="pcd-spin" />
        : noticeKind === 'info'
          ? <Info size={19} />
          : <CircleDot size={19} />

  return (
    <section
      className={`pcd-message-center is-${noticeKind} ${expanded ? 'is-log-expanded' : ''}`}
      aria-live={noticeKind === 'error' ? 'assertive' : 'polite'}
    >
      <div className="pcd-message-primary" title={notice?.message || undefined}>
        <span className="pcd-message-status-icon" aria-hidden="true">{noticeIcon}</span>
        <div className="pcd-message-copy">
          <div className="pcd-message-heading">
            <span className="pcd-message-label">{noticeLabel}</span>
            <strong>{notice?.title || '系统待命'}</strong>
          </div>
          <span className="pcd-message-detail">{notice?.message || '当前没有新的操作提醒。'}</span>
        </div>
      </div>
      <div className="pcd-message-log">
        <button
          type="button"
          className="pcd-message-log-toggle"
          onClick={onToggleExpanded}
          title={expanded ? '收起导航日志' : '展开导航历史日志'}
          aria-expanded={expanded}
        >
          <span className="pcd-message-log-title">
            <ScrollText size={15} />
            <strong>操作日志</strong>
            <i>{logs.length}</i>
            {errorCount > 0 ? <i className="is-error">{errorCount} 错误</i> : null}
          </span>
          <span className={`pcd-message-log-latest ${latestLog?.level === 'error' ? 'is-error' : ''}`}>
            {latestLog ? (
              <>
                <time>{formatLogTime(latestLog.timestamp)}</time>
                <span>{latestLog.message}</span>
              </>
            ) : '等待操作日志'}
          </span>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        {expanded ? (
          <div className="pcd-message-log-history" role="log" aria-label="导航历史日志">
            <div className="pcd-message-log-history-head">
              <strong>操作日志</strong>
              <span>最近 {logs.length} 条，最多保留 30 条</span>
            </div>
            {logs.length > 0 ? (
              logs.map((item) => (
                <div key={item.id} className={`pcd-message-log-row ${item.level === 'error' ? 'is-error' : 'is-info'}`}>
                  <time>{formatLogTime(item.timestamp)}</time>
                  <span className="pcd-message-log-level">{item.level === 'error' ? '错误' : '信息'}</span>
                  <p>{item.message}</p>
                </div>
              ))
            ) : (
              <div className="pcd-message-log-empty">暂无操作日志</div>
            )}
          </div>
        ) : null}
      </div>
    </section>
  )
}

function formatLogTime(timestamp: number) {
  return new Date(timestamp).toLocaleTimeString([], {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
