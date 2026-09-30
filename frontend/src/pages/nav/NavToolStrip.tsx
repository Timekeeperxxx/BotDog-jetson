import { PointCloudLayerSettings } from '../../components/pcd/PointCloudLayerSettings'
import { NO_HEIGHT_CLIP, type HeightClip } from '../../components/pcd/PointCloudHeightClip'
import {
  Boxes,
  CircleStop,
  Crosshair,
  Keyboard,
  Layers,
  Loader2,
  LocateFixed,
  MapPlus,
  Radar,
  Save,
  UserSearch,
} from 'lucide-react'
import type { PointCloudQualityMode, WallColorMode } from '../../types/pcdMap'
import type { FenceDetectionStatus } from '../../types/fenceDetection'
import { formatSpeed } from '../../utils/speedControl'
import { NavFenceControls } from '../../components/pcd/NavFenceControls'
import type { MappingSessionInfo } from './navPageUtils'

export type PcdLayerVisibility = {
  map: boolean
  ground: boolean
  footprint: boolean
}

type NavToolStripProps = {
  canOperate: boolean
  fenceMode: boolean
  fenceAddAvailable: boolean
  fenceDetectionStatus: FenceDetectionStatus | null
  fenceDetectionLoading: boolean
  fenceDetectionError: string | null
  currentCmd: string | null
  followRobot: boolean
  isControlling: boolean
  keyboardControlEnabled: boolean
  lastResultText: string | null
  linearSpeed: number
  mappingActive: boolean
  mappingPreflightChecking: boolean
  mappingSaving: boolean
  mappingSending: boolean
  mappingSessionInfo: MappingSessionInfo | null
  navAutoTrackEnabled: boolean
  navAutoTrackLoading: boolean
  pcdLayerPanelOpen: boolean
  pcdLayerVisibility: PcdLayerVisibility
  pointCloudQualityMode: PointCloudQualityMode
  radarChecking: boolean
  rosbagLoading: boolean
  rosbagRunning: boolean
  rosbagUsesMappingLidar: boolean
  resultMessage: string | null
  robotPoseAvailable: boolean
  selectedSceneNavigable: boolean
  selectedTaskId: string | null
  toolMode: 'none' | 'obstacle' | 'pose'
  turnSpeed: number
  webglSupported: boolean
  heightClip?: HeightClip
  onHeightClip?: (value: HeightClip) => void
  pointSize?: number
  onPointSize?: (value: number) => void
  intensityPreference?: number
  onIntensityPreference?: (value: number) => void
  wallColorMode: WallColorMode
  onCheckRadar: () => void
  onToggleFenceMode: () => void
  onSetFenceDetectionEnabled: (enabled: boolean) => void
  onToggleRosbag: () => void
  onStopSelectedTask: () => void
  onToggleFollowRobot: () => void
  onToggleKeyboardControl: () => void
  onToggleLayer: (layer: keyof PcdLayerVisibility) => void
  onToggleLayerPanel: () => void
  onSelectWallColorMode: (mode: WallColorMode) => void
  onSelectPointCloudQualityMode: (mode: PointCloudQualityMode) => void
  onToggleMapping: () => void
  onToggleNavAutoTrack: () => void
  onToolMode: (mode: 'obstacle' | 'pose') => void
}

export function NavToolStrip({
  canOperate,
  fenceMode,
  fenceAddAvailable,
  fenceDetectionStatus,
  fenceDetectionLoading,
  fenceDetectionError,
  currentCmd,
  followRobot,
  isControlling,
  keyboardControlEnabled,
  lastResultText,
  linearSpeed,
  mappingActive,
  mappingPreflightChecking,
  mappingSaving,
  mappingSending,
  mappingSessionInfo,
  navAutoTrackEnabled,
  navAutoTrackLoading,
  pcdLayerPanelOpen,
  pcdLayerVisibility,
  radarChecking,
  rosbagLoading,
  rosbagRunning,
  rosbagUsesMappingLidar,
  resultMessage,
  robotPoseAvailable,
  selectedSceneNavigable,
  selectedTaskId,
  toolMode,
  turnSpeed,
  webglSupported,
  heightClip = NO_HEIGHT_CLIP,
  onHeightClip,
  pointSize = 1,
  onPointSize,
  intensityPreference = 0,
  onIntensityPreference,
  wallColorMode,
  onCheckRadar,
  onToggleFenceMode,
  onSetFenceDetectionEnabled,
  onToggleRosbag,
  onStopSelectedTask,
  onToggleFollowRobot,
  onToggleKeyboardControl,
  onToggleLayer,
  onToggleLayerPanel,
  onSelectWallColorMode,
  onToggleMapping,
  onToggleNavAutoTrack,
  onToolMode,
}: NavToolStripProps) {
  const mappingBusy = mappingPreflightChecking || mappingSending || mappingSaving
  const mappingButtonLabel = mappingSaving
    ? '正在保存地图...'
    : mappingPreflightChecking
      ? '检查雷达中'
      : mappingSending
        ? '开始建图中'
        : mappingActive
          ? '结束建图'
          : '开始建图'

  return (
    <>
      <section className="pcd-tool-strip">
        <NavFenceControls
          adding={fenceMode}
          canAdd={fenceAddAvailable}
          canOperate={canOperate}
          status={fenceDetectionStatus}
          loading={fenceDetectionLoading}
          error={fenceDetectionError}
          onToggleAdd={onToggleFenceMode}
          onSetDetectionEnabled={onSetFenceDetectionEnabled}
        />
        <button
          className={`pcd-tool-button ${followRobot ? 'is-active' : ''}`}
          onClick={onToggleFollowRobot}
          disabled={!robotPoseAvailable}
          title={!robotPoseAvailable ? '等待机器狗定位数据' : undefined}
        >
          <LocateFixed size={15} />
          <span>{followRobot ? '解除跟随' : '视角跟随'}</span>
        </button>
        <div className="pcd-layer-control">
          <button
            className={`pcd-tool-button ${pcdLayerPanelOpen || !pcdLayerVisibility.map || !pcdLayerVisibility.ground || !pcdLayerVisibility.footprint ? 'is-active' : ''}`}
            onClick={onToggleLayerPanel}
            disabled={mappingActive}
            title={mappingActive ? '建图中显示实时点云，场景图层开关暂不可用' : '选择显示的 PCD 图层'}
            aria-expanded={pcdLayerPanelOpen}
            aria-controls="pcd-layer-popover"
          >
            <Layers size={15} />
            <span>点云图层</span>
          </button>
          {pcdLayerPanelOpen && !mappingActive ? (
            <div id="pcd-layer-popover" className="pcd-layer-popover" role="group" aria-label="PCD 图层显示开关">
              <PointCloudLayerSettings
                pcdLayerVisibility={pcdLayerVisibility}
                onToggleLayer={onToggleLayer}
                wallColorMode={wallColorMode}
                onSelectWallColorMode={onSelectWallColorMode}
                heightClip={heightClip}
                onHeightClip={onHeightClip}
                pointSize={pointSize}
                onPointSize={onPointSize}
                intensityPreference={intensityPreference}
                onIntensityPreference={onIntensityPreference}
              />
            </div>
          ) : null}
        </div>
        <button
          className={`pcd-tool-button ${toolMode === 'obstacle' ? 'is-active' : ''}`}
          onClick={() => onToolMode('obstacle')}
        >
          <Boxes size={15} />
          <span>添加障碍物</span>
        </button>
        <button
          className={`pcd-tool-button ${toolMode === 'pose' ? 'is-active' : ''}`}
          onClick={() => onToolMode('pose')}
          disabled={!canOperate || !selectedSceneNavigable || !webglSupported}
          title={!webglSupported ? '当前浏览器无法使用 3D 点云标记' : !selectedSceneNavigable ? '当前场景缺少 ground.pcd' : undefined}
        >
          <Crosshair size={15} />
          <span>重定位</span>
        </button>
        <button
          className={`pcd-tool-button ${keyboardControlEnabled ? 'is-active' : ''}`}
          onClick={onToggleKeyboardControl}
          disabled={!canOperate}
          title={keyboardControlEnabled ? '关闭键盘控制' : '开启键盘控制，方向键调节速度，W/S/Q/E 控制移动'}
        >
          <Keyboard size={15} />
          <span>{keyboardControlEnabled ? '控制中' : '移动控制'}</span>
        </button>
        <button
          className={`pcd-tool-button pcd-mapping-button ${mappingActive ? 'is-active' : ''} ${mappingSaving ? 'is-saving' : ''}`}
          onClick={onToggleMapping}
          disabled={mappingBusy || !canOperate}
          title={mappingActive ? '结束当前建图并保存地图' : '检查雷达状态后开始建图'}
        >
          {mappingBusy
            ? <Loader2 size={15} className="pcd-spin" />
            : mappingActive
              ? <Save size={15} />
              : <MapPlus size={15} />}
          <span>{mappingButtonLabel}</span>
        </button>
        <button
          className="pcd-tool-button pcd-stop-task-button"
          onClick={onStopSelectedTask}
          disabled={!canOperate || !selectedTaskId}
          title={!selectedTaskId ? '先选择一个任务' : '停止当前选中的任务'}
        >
          <CircleStop size={15} />
          <span>停止任务</span>
        </button>
        <button
          className="pcd-tool-button"
          onClick={onCheckRadar}
          disabled={!canOperate || radarChecking || rosbagLoading}
          title="检查雷达 ROS2 topic、发布者和数据频率"
        >
          {radarChecking ? <Loader2 size={15} className="pcd-spin" /> : <Radar size={15} />}
          <span>{radarChecking ? '检查中' : '检查雷达'}</span>
        </button>
        <button
          className={`pcd-tool-button ${rosbagRunning ? 'is-active' : ''}`}
          onClick={onToggleRosbag}
          disabled={!canOperate || rosbagLoading || radarChecking}
          title={
            rosbagRunning
              ? rosbagUsesMappingLidar
                ? '停止录包；当前录包复用建图中的雷达驱动'
                : '停止录包并安全写入 metadata.yaml'
              : mappingActive
                ? '开始录包，复用当前建图的雷达驱动'
                : '开始录包；空闲时会按需启动雷达驱动'
          }
        >
          {rosbagLoading
            ? <Loader2 size={15} className="pcd-spin" />
            : rosbagRunning
              ? <CircleStop size={15} />
              : <Save size={15} />}
          <span>{rosbagLoading ? '处理中' : rosbagRunning ? '停止录包' : '开始录包'}</span>
        </button>
        <button
          className={`pcd-tool-button ${navAutoTrackEnabled ? 'is-active' : ''}`}
          onClick={onToggleNavAutoTrack}
          disabled={!canOperate || navAutoTrackLoading}
          title="导航任务中检测到陌生人时自动暂停导航并进入自动跟踪"
        >
          {navAutoTrackLoading ? <Loader2 size={15} className="pcd-spin" /> : <UserSearch size={15} />}
          <span>{navAutoTrackEnabled ? '跟踪联动开' : '跟踪联动关'}</span>
        </button>
        {keyboardControlEnabled && (
          <div className="pcd-keyboard-hint">
            <span>
              {isControlling ? `控制中: ${currentCmd}` : '方向键调速'}
              {' · '}
              前后 {formatSpeed(linearSpeed)} m/s
              {' · '}
              转向 {formatSpeed(turnSpeed)} rad/s
            </span>
            {resultMessage ? <small>{resultMessage}</small> : null}
            {!resultMessage && lastResultText ? <small>{lastResultText}</small> : null}
          </div>
        )}
      </section>
      {mappingSessionInfo ? (
        <section className="pcd-mapping-session">
          <strong>{mappingSaving ? '正在保存场景' : '当前建图场景'}：{mappingSessionInfo.sceneName}</strong>
          <span>场景保存路径：{mappingSessionInfo.mapDir}</span>
        </section>
      ) : null}
    </>
  )
}
