import { Battery, Crosshair, Loader2 } from 'lucide-react'
import { NavWaypointPanel } from '../../components/pcd/NavWaypointPanel'
import { PointCloudTopDownCanvas } from '../../components/pcd/PointCloudTopDownCanvas'
import type { GlobalPath, RobotPose } from '../../types/navState'
import type { NavWaypoint, PcdBounds, PcdSceneLayerRole, PointCloudPoints } from '../../types/pcdMap'

type NavPageHeaderProps = {
  addMode: boolean
  batteryPct: number | null | undefined
  canOperate: boolean
  loading: boolean
  restartLocalizationSending: boolean
  selectedSceneNavigable: boolean
  webglSupported: boolean
  previewAvailable: boolean
  onRestartLocalization: () => void
  onToggleWaypointMode: () => void
}

export function NavPageHeader({
  addMode,
  batteryPct,
  canOperate,
  loading,
  restartLocalizationSending,
  selectedSceneNavigable,
  webglSupported,
  previewAvailable,
  onRestartLocalization,
  onToggleWaypointMode,
}: NavPageHeaderProps) {
  const unavailableTitle = !webglSupported
    ? '当前浏览器无法使用 3D 点云标记'
    : !selectedSceneNavigable
      ? '当前场景缺少 ground.pcd'
      : undefined

  return (
    <header className="pcd-demo-header">
      <div className="pcd-title-row">
        <div className="pcd-title-block">
          <h1>BotDog 导航巡逻</h1>
          <p>from 西部泰力</p>
        </div>
      </div>
      <div className="pcd-header-actions">
        <div className="pcd-battery-status" title="机器狗剩余电量">
          <Battery size={16} />
          <span>电量</span>
          <strong>{batteryPct != null ? `${batteryPct.toFixed(0)}%` : '--'}</strong>
        </div>
        {loading ? (
          <span className="pcd-loading">
            <Loader2 size={16} /> 加载中
          </span>
        ) : null}
        <button
          className="pcd-secondary-button"
          disabled={!canOperate || restartLocalizationSending || !selectedSceneNavigable || !webglSupported}
          onClick={onRestartLocalization}
          title={unavailableTitle}
        >
          {restartLocalizationSending ? '重启中...' : '重启导航定位'}
        </button>
        <button
          className={`pcd-primary-button ${addMode ? 'is-active' : ''}`}
          disabled={!previewAvailable || !selectedSceneNavigable || !webglSupported}
          onClick={onToggleWaypointMode}
          title={unavailableTitle}
        >
          <Crosshair size={16} />
          {addMode ? '退出标点' : '添加导航点'}
        </button>
      </div>
    </header>
  )
}

export type PointCloudLayer = {
  role: PcdSceneLayerRole
  points: PointCloudPoints
  intensity?: Uint8Array
  coordinateSpace?: 'map' | 'three'
}

type NavRightRailProps = {
  bounds: PcdBounds | null
  canOperate: boolean
  estopSending: boolean
  executionPath: GlobalPath | null
  globalPath: GlobalPath | null
  layers: PointCloudLayer[]
  navigatingWaypointId: string | null
  robotPose: RobotPose | null
  sceneNavigable: boolean
  viewKey: string
  waypoints: NavWaypoint[]
  onAddWaypoint: (pos: { x: number; y: number; z: number; yaw: number }) => void
  onDeleteWaypoint: (waypointId: string) => void
  onEmergencyStop: () => void
  onGoToWaypoint: (waypointId: string) => void
  onMouseMapPositionChange: (pos: { x: number; y: number } | null) => void
  onSetPose: (pos: { x: number; y: number; z: number; yaw: number }) => void
}

export function NavRightRail({
  bounds,
  canOperate,
  estopSending,
  executionPath,
  globalPath,
  layers,
  navigatingWaypointId,
  robotPose,
  sceneNavigable,
  viewKey,
  waypoints,
  onAddWaypoint,
  onDeleteWaypoint,
  onEmergencyStop,
  onGoToWaypoint,
  onMouseMapPositionChange,
  onSetPose,
}: NavRightRailProps) {
  return (
    <aside className="pcd-right-rail">
      <PointCloudTopDownCanvas
        layers={layers}
        viewKey={viewKey}
        bounds={bounds}
        waypoints={waypoints}
        robotPose={robotPose}
        globalPath={globalPath}
        executionPath={executionPath}
        mode="none"
        waypointZ={0}
        onMouseMapPositionChange={onMouseMapPositionChange}
        onAddWaypoint={onAddWaypoint}
        onSetPose={onSetPose}
      />
      <NavWaypointPanel
        waypoints={waypoints}
        navigatingWaypointId={navigatingWaypointId}
        sceneNavigable={sceneNavigable}
        onGoTo={onGoToWaypoint}
        onDelete={onDeleteWaypoint}
      />
      <section className="pcd-rail-footer">
        <button
          className="pcd-estop-button"
          onClick={onEmergencyStop}
          disabled={estopSending || !canOperate}
        >
          {estopSending ? '急停发送中' : '导航急停'}
        </button>
      </section>
    </aside>
  )
}
