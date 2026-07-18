import { PointCloud3DViewer } from '../../components/pcd/PointCloud3DViewer'
import type { GlobalPath, RobotPose } from '../../types/navState'
import type { NavWaypoint, PcdSceneTileManifest, PointCloudQualityMode, WallColorMode } from '../../types/pcdMap'
import type { PointCloudLayer } from './NavPageShell'

type NavMainViewerProps = {
  centerHeight: number | null
  executionPath: GlobalPath | null
  followRobot: boolean
  globalPath: GlobalPath | null
  layers: PointCloudLayer[]
  mode: 'none' | 'waypoint' | 'pose'
  pointCloudQualityMode: PointCloudQualityMode
  robotPose: RobotPose | null
  viewKey: string
  wallColorMode: WallColorMode
  tiledScene: PcdSceneTileManifest | null
  tileVisibility: {
    ground: boolean
    wall: boolean
    footprint_fill: boolean
  }
  waypoints: NavWaypoint[]
  webglSupported: boolean
  onAddWaypoint: (pos: { x: number; y: number; z: number; yaw: number }) => void
  onGroundPointerChange: (pos: { x: number; y: number } | null) => void
  onSetPose: (pos: { x: number; y: number; z: number; yaw: number }) => void
}

export function NavMainViewer({
  centerHeight,
  executionPath,
  followRobot,
  globalPath,
  layers,
  mode,
  pointCloudQualityMode,
  robotPose,
  viewKey,
  wallColorMode,
  tiledScene,
  tileVisibility,
  waypoints,
  webglSupported,
  onAddWaypoint,
  onGroundPointerChange,
  onSetPose,
}: NavMainViewerProps) {
  if (!webglSupported) {
    return (
      <div className="flex min-h-[520px] items-center justify-center rounded-2xl border border-white/10 bg-[radial-gradient(circle_at_top,rgba(16,24,32,0.92),rgba(4,7,10,0.98))] px-6 text-center">
        <div className="max-w-2xl space-y-4">
          <div className="text-2xl font-black text-white">当前浏览器未启用 WebGL，无法渲染三维点云地图。</div>
          <div className="text-sm leading-7 text-zinc-300">
            <div>请尝试：</div>
            <div>- 使用电脑浏览器访问本页面</div>
            <div>- 在开发板 Chromium 中启用 `chrome://flags` → `Override software rendering list`</div>
            <div>- 使用启动参数 `--ignore-gpu-blocklist --enable-webgl --use-gl=egl`</div>
            <div>- 检查 `chrome://gpu` 中 WebGL/WebGL2 是否可用</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <PointCloud3DViewer
      layers={layers}
      qualityMode={pointCloudQualityMode}
      tiledScene={tiledScene}
      tileVisibility={tileVisibility}
      viewKey={viewKey}
      wallColorMode={wallColorMode}
      waypoints={waypoints}
      robotPose={robotPose}
      globalPath={globalPath}
      executionPath={executionPath}
      mode={mode}
      followRobot={followRobot}
      centerHeight={centerHeight}
      onGroundPointerChange={onGroundPointerChange}
      onAddWaypoint={onAddWaypoint}
      onSetPose={onSetPose}
    />
  )
}
