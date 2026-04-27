import { useCallback, useEffect, useState } from 'react'
import { Crosshair, Loader2 } from 'lucide-react'
import { getNavState } from '../api/navApi'
import {
  createWaypoint,
  deleteWaypoint,
  getPcdMetadata,
  getPcdPreview,
  listPcdMaps,
  listWaypoints,
} from '../api/pcdMapApi'
import { NavWaypointPanel } from '../components/pcd/NavWaypointPanel'
import { PcdFileListPanel } from '../components/pcd/PcdFileListPanel'
import { PcdMetadataPanel } from '../components/pcd/PcdMetadataPanel'
import { PointCloud3DViewer } from '../components/pcd/PointCloud3DViewer'
import { PointCloudTopDownCanvas } from '../components/pcd/PointCloudTopDownCanvas'
import { useNavWebSocket } from '../hooks/useNavWebSocket'
import type { NavWaypoint, PcdMapItem, PcdMetadata, PcdPreview } from '../types/pcdMap'

type LogItem = {
  id: number
  level: 'info' | 'error'
  message: string
}

function nowText() {
  return new Date().toLocaleTimeString()
}

export function PcdMapDemoPage() {
  const [maps, setMaps] = useState<PcdMapItem[]>([])
  const [root, setRoot] = useState('')
  const [selectedMapId, setSelectedMapId] = useState<string | null>(null)
  const [metadata, setMetadata] = useState<PcdMetadata | null>(null)
  const [preview, setPreview] = useState<PcdPreview | null>(null)
  const [waypoints, setWaypoints] = useState<NavWaypoint[]>([])
  const [loading, setLoading] = useState(false)
  const [addMode, setAddMode] = useState(false)
  const [mouseMapPosition, setMouseMapPosition] = useState<{ x: number; y: number } | null>(null)
  const [logs, setLogs] = useState<LogItem[]>([])
  const navWs = useNavWebSocket()

  const addLog = useCallback((message: string, level: LogItem['level'] = 'info') => {
    setLogs((items) => [
      { id: Date.now() + Math.random(), level, message: `${nowText()} ${message}` },
      ...items,
    ].slice(0, 30))
  }, [])

  const refreshMaps = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listPcdMaps()
      setMaps(data.items)
      setRoot(data.root)
      addLog(`已刷新 PCD 目录，共 ${data.items.length} 个文件`)
    } catch (error) {
      addLog(error instanceof Error ? error.message : '获取 PCD 列表失败', 'error')
    } finally {
      setLoading(false)
    }
  }, [addLog])

  const selectMap = useCallback(async (mapId: string) => {
    setLoading(true)
    setSelectedMapId(mapId)
    setMetadata(null)
    setPreview(null)
    setWaypoints([])
    setAddMode(false)

    try {
      const nextMetadata = await getPcdMetadata(mapId)
      setMetadata(nextMetadata)
      addLog(`已读取 metadata: ${mapId}`)

      if (nextMetadata.supported === false) {
        addLog(nextMetadata.message || '当前 PCD 暂不支持预览', 'error')
        return
      }

      const [nextPreview, nextWaypoints] = await Promise.all([
        getPcdPreview(mapId, 100000),
        listWaypoints(mapId),
      ])
      setPreview(nextPreview)
      setWaypoints(nextWaypoints.items)
      addLog(`已加载预览点云 ${nextPreview.points.length.toLocaleString()} 点`)
    } catch (error) {
      addLog(error instanceof Error ? error.message : `加载地图失败: ${mapId}`, 'error')
    } finally {
      setLoading(false)
    }
  }, [addLog])

  const handleAddWaypoint = useCallback(async (pos: { x: number; y: number }) => {
    if (!selectedMapId) return

    const defaultName = `巡检点${waypoints.length + 1}`
    const name = window.prompt('导航点名称', defaultName)?.trim()
    if (!name) return

    try {
      await createWaypoint(selectedMapId, {
        name,
        x: pos.x,
        y: pos.y,
        z: 0,
        yaw: 0,
        frame_id: 'map',
      })
      const nextWaypoints = await listWaypoints(selectedMapId)
      setWaypoints(nextWaypoints.items)
      setAddMode(false)
      addLog(`已保存导航点 ${name}: x=${pos.x.toFixed(3)}, y=${pos.y.toFixed(3)}`)
    } catch (error) {
      addLog(error instanceof Error ? error.message : '保存导航点失败', 'error')
    }
  }, [addLog, selectedMapId, waypoints.length])

  const handleDeleteWaypoint = useCallback(async (waypointId: string) => {
    if (!selectedMapId) return

    try {
      await deleteWaypoint(selectedMapId, waypointId)
      const nextWaypoints = await listWaypoints(selectedMapId)
      setWaypoints(nextWaypoints.items)
      addLog(`已删除导航点 ${waypointId}`)
    } catch (error) {
      addLog(error instanceof Error ? error.message : '删除导航点失败', 'error')
    }
  }, [addLog, selectedMapId])

  useEffect(() => {
    void refreshMaps()
  }, [refreshMaps])

  useEffect(() => {
    let cancelled = false

    async function loadNavState() {
      try {
        const state = await getNavState()
        if (cancelled) return
        navWs.setInitialState({
          robotPose: state.robot_pose,
          localizationStatus: state.localization_status,
          navigationStatus: state.navigation_status,
        })
        addLog('已同步导航实时状态')
      } catch (error) {
        if (!cancelled) {
          addLog(error instanceof Error ? error.message : '同步导航状态失败', 'error')
        }
      }
    }

    void loadNavState()
    return () => {
      cancelled = true
    }
  }, [addLog])

  const robotPose = navWs.robotPose
  const localizationStatus = navWs.localizationStatus

  return (
    <main className="pcd-demo-page">
      <header className="pcd-demo-header">
        <div>
          <h1>BotDog 导航巡逻 PCD Demo</h1>
          <p>独立调试页 · PCD 读取、点云预览、map 坐标标点</p>
        </div>
        <div className="pcd-header-actions">
          {loading ? (
            <span className="pcd-loading">
              <Loader2 size={16} /> 加载中
            </span>
          ) : null}
          <button
            className={`pcd-primary-button ${addMode ? 'is-active' : ''}`}
            disabled={!preview}
            onClick={() => setAddMode((value) => !value)}
          >
            <Crosshair size={16} />
            {addMode ? '退出标点' : '添加导航点'}
          </button>
        </div>
      </header>

      <div className="pcd-demo-grid">
        <PcdFileListPanel
          maps={maps}
          root={root}
          selectedMapId={selectedMapId}
          loading={loading}
          onRefresh={refreshMaps}
          onSelect={selectMap}
        />

        <section className="pcd-center-stage">
          <PointCloud3DViewer
            points={preview?.points || []}
            waypoints={waypoints}
            robotPose={robotPose}
          />
          <PointCloudTopDownCanvas
            points={preview?.points || []}
            bounds={preview?.bounds || metadata?.bounds || null}
            waypoints={waypoints}
            robotPose={robotPose}
            addMode={addMode}
            onMouseMapPositionChange={setMouseMapPosition}
            onAddWaypoint={handleAddWaypoint}
          />
        </section>

        <aside className="pcd-side-stack">
          <PcdMetadataPanel metadata={metadata} mouseMapPosition={mouseMapPosition} />
          <section className="pcd-panel">
            <div className="pcd-panel-header">
              <div>
                <h2>机器人状态</h2>
                <p>{navWs.connected ? 'WebSocket 已连接' : 'WebSocket 未连接'}</p>
              </div>
            </div>
            {robotPose ? (
              <div className="pcd-metadata-grid">
                <span>X / Y</span>
                <strong>{robotPose.x.toFixed(3)}, {robotPose.y.toFixed(3)}</strong>
                <span>Z</span>
                <strong>{robotPose.z.toFixed(3)}</strong>
                <span>Yaw</span>
                <strong>{robotPose.yaw.toFixed(3)} rad</strong>
                <span>Frame</span>
                <strong>{robotPose.frame_id}</strong>
                <span>Source</span>
                <strong>{robotPose.source}</strong>
                <span>更新时间</span>
                <strong>{new Date(robotPose.timestamp * 1000).toLocaleTimeString()}</strong>
              </div>
            ) : (
              <div className="pcd-empty">未收到机器人位姿</div>
            )}
            {robotPose && robotPose.frame_id !== 'map' ? (
              <div className="pcd-warning">当前位姿不是 map 坐标系：{robotPose.frame_id}</div>
            ) : null}
            {localizationStatus ? (
              <div className={localizationStatus.status === 'ok' ? 'pcd-bounds' : 'pcd-warning'}>
                {localizationStatus.message}
              </div>
            ) : null}
          </section>
          <NavWaypointPanel waypoints={waypoints} onDelete={handleDeleteWaypoint} />
        </aside>
      </div>

      <section className="pcd-log-panel">
        {logs.length === 0 ? (
          <span>等待操作日志</span>
        ) : (
          logs.map((log) => (
            <span key={log.id} className={log.level === 'error' ? 'is-error' : ''}>
              {log.message}
            </span>
          ))
        )}
      </section>
    </main>
  )
}
