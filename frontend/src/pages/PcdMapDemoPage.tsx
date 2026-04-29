import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Boxes,
  ChevronDown,
  ChevronUp,
  Crosshair,
  Keyboard,
  Loader2,
  LocateFixed,
  Square,
} from 'lucide-react'
import { getNavState } from '../api/navApi'
import {
  createWaypoint,
  deleteWaypoint,
  goToWaypoint,
  getPcdMetadata,
  getPcdPreview,
  listPcdMaps,
  listWaypoints,
  notifyNavPageOpen,
  triggerNavEmergencyStop,
} from '../api/pcdMapApi'
import { NavWaypointPanel } from '../components/pcd/NavWaypointPanel'
import { PcdFileListPanel } from '../components/pcd/PcdFileListPanel'
import { PointCloud3DViewer } from '../components/pcd/PointCloud3DViewer'
import { PointCloudTopDownCanvas } from '../components/pcd/PointCloudTopDownCanvas'
import { useRobotControl, type RobotCommand } from '../hooks/useRobotControl'
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
  const previewPointLimit = 15000
  const [maps, setMaps] = useState<PcdMapItem[]>([])
  const [root, setRoot] = useState('')
  const [selectedMapId, setSelectedMapId] = useState<string | null>(null)
  const [metadata, setMetadata] = useState<PcdMetadata | null>(null)
  const [preview, setPreview] = useState<PcdPreview | null>(null)
  const [waypoints, setWaypoints] = useState<NavWaypoint[]>([])
  const [loading, setLoading] = useState(false)
  const [addMode, setAddMode] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [infoOpen, setInfoOpen] = useState(true)
  const [followRobot, setFollowRobot] = useState(false)
  const [toolMode, setToolMode] = useState<'none' | 'obstacle' | 'pose'>('none')
  const [waypointZ, setWaypointZ] = useState(-0.83)
  const [navigatingWaypointId, setNavigatingWaypointId] = useState<string | null>(null)
  const [estopSending, setEstopSending] = useState(false)
  const [mouseMapPosition, setMouseMapPosition] = useState<{ x: number; y: number } | null>(null)
  const [logs, setLogs] = useState<LogItem[]>([])
  const selectRequestRef = useRef(0)
  const navWs = useNavWebSocket()
  const {
    startCommand,
    stopCommand,
    isControlling,
    currentCmd,
    lastResult,
    resultMessage,
  } = useRobotControl()

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
    const requestId = ++selectRequestRef.current
    setLoading(true)
    setSelectedMapId(mapId)
    setMetadata(null)
    setPreview(null)
    setWaypoints([])
    setAddMode(false)

    try {
      const nextMetadata = await getPcdMetadata(mapId)
      if (requestId !== selectRequestRef.current) return
      setMetadata(nextMetadata)
      addLog(`已读取 metadata: ${mapId}`)

      if (nextMetadata.supported === false) {
        addLog(nextMetadata.message || '当前 PCD 暂不支持预览', 'error')
        return
      }

      const [nextPreview, nextWaypoints] = await Promise.all([
        getPcdPreview(mapId, previewPointLimit),
        listWaypoints(mapId),
      ])
      if (requestId !== selectRequestRef.current) return
      setPreview(nextPreview)
      setWaypoints(nextWaypoints.items)
      addLog(`已加载预览点云 ${nextPreview.points.length.toLocaleString()} 点`)
    } catch (error) {
      if (requestId !== selectRequestRef.current) return
      addLog(error instanceof Error ? error.message : `加载地图失败: ${mapId}`, 'error')
    } finally {
      if (requestId === selectRequestRef.current) {
        setLoading(false)
      }
    }
  }, [addLog, previewPointLimit])

  const handleAddWaypoint = useCallback(async (pos: { x: number; y: number; z: number; yaw: number }) => {
    if (!selectedMapId) return

    const defaultName = `巡检点${waypoints.length + 1}`
    const name = window.prompt('导航点名称', defaultName)?.trim()
    if (!name) return

    try {
      await createWaypoint(selectedMapId, {
        name,
        x: pos.x,
        y: pos.y,
        z: pos.z,
        yaw: pos.yaw,
        frame_id: 'map',
      })
      const nextWaypoints = await listWaypoints(selectedMapId)
      setWaypoints(nextWaypoints.items)
      setAddMode(false)
      addLog(
        `已保存导航点 ${name}: x=${pos.x.toFixed(3)}, y=${pos.y.toFixed(3)}, z=${pos.z.toFixed(3)}, yaw=${pos.yaw.toFixed(3)}`,
      )
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

  const handleGoToWaypoint = useCallback(async (waypointId: string) => {
    if (!selectedMapId) return

    setNavigatingWaypointId(waypointId)
    try {
      const result = await goToWaypoint(selectedMapId, waypointId)
      const waypoint = waypoints.find((item) => item.id === waypointId)
      addLog(`已发布导航目标 ${waypoint?.name || waypointId} 到 ${result.topic}`)
    } catch (error) {
      addLog(error instanceof Error ? error.message : '发布导航目标失败', 'error')
    } finally {
      setNavigatingWaypointId(null)
    }
  }, [addLog, selectedMapId, waypoints])

  const handleEmergencyStop = useCallback(async () => {
    setEstopSending(true)
    try {
      const result = await triggerNavEmergencyStop()
      addLog(`已发布导航急停到 ${result.topic}`, 'error')
    } catch (error) {
      addLog(error instanceof Error ? error.message : '发布导航急停失败', 'error')
    } finally {
      setEstopSending(false)
    }
  }, [addLog])

  useEffect(() => {
    void refreshMaps()
  }, [refreshMaps])

  useEffect(() => {
    if (selectedMapId || maps.length === 0) return
    void selectMap(maps[0].id)
  }, [maps, selectedMapId, selectMap])

  useEffect(() => {
    let cancelled = false

    async function sendPageOpenSignal() {
      try {
        const result = await notifyNavPageOpen()
        if (!cancelled) {
          addLog(`已发送页面启动信号到 ${result.topic}`)
        }
      } catch (error) {
        if (!cancelled) {
          addLog(error instanceof Error ? error.message : '发送页面启动信号失败', 'error')
        }
      }
    }

    void sendPageOpenSignal()
    return () => {
      cancelled = true
    }
  }, [addLog])

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

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((event.target as HTMLElement).tagName)) return
      if (event.repeat) return

      let cmd: RobotCommand | null = null
      switch (event.key.toLowerCase()) {
        case 'w':
        case 'arrowup':
          cmd = 'forward'
          break
        case 's':
        case 'arrowdown':
          cmd = 'backward'
          break
        case 'a':
          cmd = 'strafe_left'
          break
        case 'd':
          cmd = 'strafe_right'
          break
        case 'q':
        case 'arrowleft':
          cmd = 'left'
          break
        case 'e':
        case 'arrowright':
          cmd = 'right'
          break
        case 'control':
          cmd = 'sit'
          break
        case 'shift':
          cmd = 'stand'
          break
      }

      if (cmd) {
        event.preventDefault()
        startCommand(cmd)
      }
    }

    const handleKeyUp = (event: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((event.target as HTMLElement).tagName)) return

      let cmd: RobotCommand | null = null
      switch (event.key.toLowerCase()) {
        case 'w':
        case 'arrowup':
          cmd = 'forward'
          break
        case 's':
        case 'arrowdown':
          cmd = 'backward'
          break
        case 'a':
          cmd = 'strafe_left'
          break
        case 'd':
          cmd = 'strafe_right'
          break
        case 'q':
        case 'arrowleft':
          cmd = 'left'
          break
        case 'e':
        case 'arrowright':
          cmd = 'right'
          break
        case 'control':
          cmd = 'sit'
          break
        case 'shift':
          cmd = 'stand'
          break
      }

      if (cmd && currentCmd === cmd) {
        event.preventDefault()
        stopCommand()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)

    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
    }
  }, [currentCmd, startCommand, stopCommand])

  const handleToolMode = useCallback((nextMode: 'obstacle' | 'pose') => {
    setToolMode((current) => {
      const resolved = current === nextMode ? 'none' : nextMode
      addLog(
        resolved === 'none'
          ? '已退出工具模式'
          : resolved === 'obstacle'
            ? '已切换到添加障碍物模式'
            : '已切换到设置位姿模式',
      )
      return resolved
    })
  }, [addLog])

  return (
    <main className="pcd-demo-page">
      <header className="pcd-demo-header">
        <div className="pcd-title-row">
          <div className="pcd-title-block">
            <h1>BotDog 导航巡逻</h1>
            <p>PCD 预览、标点、导航、位姿和日志统一压缩到单屏工作区</p>
          </div>
        </div>
        <div className="pcd-header-actions">
          {loading ? (
            <span className="pcd-loading">
              <Loader2 size={16} /> 加载中
            </span>
          ) : null}
          <label className="pcd-z-control">
            <span>Z</span>
            <input
              type="number"
              step="0.05"
              value={waypointZ}
              disabled={!preview}
              onChange={(event) => setWaypointZ(Number(event.target.value) || 0)}
            />
          </label>
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

      <div className="pcd-workspace">
        <section className="pcd-main-stage">
          <div className="pcd-main-viewer">
            <PointCloud3DViewer
              points={preview?.points || []}
              waypoints={waypoints}
              robotPose={robotPose}
              followRobot={followRobot}
            />
          </div>
          <div className={`pcd-drawer ${drawerOpen ? 'is-open' : 'is-closed'}`}>
            <button
              className="pcd-drawer-toggle"
              onClick={() => setDrawerOpen((value) => !value)}
              title={drawerOpen ? '收起地图选择' : '展开地图选择'}
            >
              <span>地图选择</span>
            </button>
            <div className="pcd-drawer-body">
              <PcdFileListPanel
                maps={maps}
                root={root}
                selectedMapId={selectedMapId}
                loading={loading}
                onRefresh={refreshMaps}
                onSelect={selectMap}
              />
            </div>
          </div>

          <div className="pcd-overlay-stack">
            <section className={`pcd-panel pcd-floating-panel pcd-info-drawer ${infoOpen ? 'is-open' : 'is-closed'}`}>
              <button
                className="pcd-info-toggle"
                onClick={() => setInfoOpen((value) => !value)}
                title={infoOpen ? '收起地图和位姿信息' : '展开地图和位姿信息'}
              >
                <div>
                  <strong>地图信息 / 机器狗坐标</strong>
                  <span>{metadata?.name || '未选择地图'}</span>
                </div>
                {infoOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {infoOpen ? (
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
                    </div>
                  ) : (
                    <div className="pcd-empty">选择地图后显示地图信息和机器狗位姿</div>
                  )}
                  {metadata?.supported === false ? (
                    <div className="pcd-warning">{metadata.message || '当前 PCD 类型暂不支持预览'}</div>
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
                  {localizationStatus ? (
                    <div className={localizationStatus.status === 'ok' ? 'pcd-bounds' : 'pcd-warning'}>
                      {localizationStatus.message}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </section>
          </div>

          <section className="pcd-tool-strip">
            <button
              className={`pcd-tool-button ${followRobot ? 'is-active' : ''}`}
              onClick={() => {
                setFollowRobot((value) => {
                  const nextValue = !value
                  addLog(nextValue ? '已开启视角跟随' : '已关闭视角跟随')
                  return nextValue
                })
              }}
            >
              <LocateFixed size={15} />
              <span>视角跟随</span>
            </button>
            <button
              className={`pcd-tool-button ${toolMode === 'obstacle' ? 'is-active' : ''}`}
              onClick={() => handleToolMode('obstacle')}
            >
              <Boxes size={15} />
              <span>添加障碍物</span>
            </button>
            <button
              className={`pcd-tool-button ${toolMode === 'pose' ? 'is-active' : ''}`}
              onClick={() => handleToolMode('pose')}
            >
              <Square size={15} />
              <span>设置位姿</span>
            </button>
            <div className="pcd-keyboard-hint">
              <Keyboard size={15} />
              <span>{isControlling ? `键盘控制中: ${currentCmd}` : '键盘控制: WASD / QE / Shift / Ctrl'}</span>
              {resultMessage ? <small>{resultMessage}</small> : null}
              {!resultMessage && lastResult ? <small>{lastResult.result}</small> : null}
            </div>
          </section>
        </section>

        <aside className="pcd-right-rail">
          <PointCloudTopDownCanvas
            points={preview?.points || []}
            bounds={preview?.bounds || metadata?.bounds || null}
            waypoints={waypoints}
            robotPose={robotPose}
            addMode={addMode}
            waypointZ={waypointZ}
            onMouseMapPositionChange={setMouseMapPosition}
            onAddWaypoint={handleAddWaypoint}
          />
          <NavWaypointPanel
            waypoints={waypoints}
            navigatingWaypointId={navigatingWaypointId}
            onGoTo={handleGoToWaypoint}
            onDelete={handleDeleteWaypoint}
          />
          <section className="pcd-rail-footer">
            <button
              className="pcd-estop-button"
              onClick={handleEmergencyStop}
              disabled={estopSending}
            >
              {estopSending ? '急停发送中' : '导航急停'}
            </button>
          </section>
        </aside>

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
      </div>
    </main>
  )
}
