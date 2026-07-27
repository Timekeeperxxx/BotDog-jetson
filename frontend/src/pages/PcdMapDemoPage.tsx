import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  createWaypoint,
  deleteWaypoint,
  goToWaypoint,
  listWaypoints,
  deletePcdScene,
  checkRadarHealth,
  getNavAutoTrackMode,
  getRosbagRecordingStatus,
  restartNavigationLocalization,
  setLocalizationPose,
  setNavAutoTrackMode,
  setRosbagRecordingEnabled,
  triggerNavEmergencyStop,
  waitInitialposeReady,
  waitNavigationRuntimeReady,
} from '../api/pcdMapApi'
import { detectWebGLSupport } from '../components/pcd/webglSupport'
import { useRobotControl } from '../hooks/useRobotControl'
import { useKeyboardRobotControl } from '../hooks/useKeyboardRobotControl'
import { useBotDogWebSocket } from '../hooks/useBotDogWebSocket'
import { useNavWebSocket } from '../hooks/useNavWebSocket'
import { useMappingCloudWebSocket } from '../hooks/useMappingCloudWebSocket'
import { hasAuthSession, hasRole, useAuthState } from '../stores/authStore'
import type {
  LocalizationPosePayload,
  NavWaypoint,
  PcdSceneItem,
  PointCloudQualityMode,
  RosbagRecordingResponse,
  WallColorMode,
} from '../types/pcdMap'
import { validateWaypointName } from '../utils/navWaypointValidation'
import { MIN_MAPPING_RUNTIME_SECONDS, useNavMappingControls } from './nav/useNavMappingControls'
import { useNavPointCloudViewModel } from './nav/useNavPointCloudViewModel'
import { useNavScenes } from './nav/useNavScenes'
import { useNavTasks } from './nav/useNavTasks'
import {
  GoToWaypointConfirmDialog,
  MappingStartDialog,
  MappingStopConfirmDialog,
  SceneDeleteConfirmDialog,
} from './nav/NavPageDialogs'
import { NavDrawerCluster } from './nav/NavDrawerCluster'
import { NavMainViewer } from './nav/NavMainViewer'
import { NavMessageCenter, SceneInfoDrawer } from './nav/NavPageStatusPanels'
import { NavPageHeader, NavRightRail } from './nav/NavPageShell'
import { NavToolStrip, type PcdLayerVisibility } from './nav/NavToolStrip'
import {
  formatRestartHealthLog,
  getRelocationNotice,
  summarizeLocalizationStatus,
} from './nav/navPageUtils'
import type { LogItem, RelocationPromptState } from './nav/navPageUtils'

type OperationNotice = {
  title: string
  message: string
  kind: 'info' | 'error'
}

export function PcdMapDemoPage() {
  useAuthState()
  const canOperate = hasAuthSession() && hasRole('operator')
  const [pcdLayerPanelOpen, setPcdLayerPanelOpen] = useState(false)
  const [pcdLayerVisibility, setPcdLayerVisibility] = useState<PcdLayerVisibility>({
    map: true,
    ground: true,
    footprint: true,
  })
  const [wallColorMode, setWallColorMode] = useState<WallColorMode>('intensity')
  const [pointCloudQualityMode, setPointCloudQualityMode] = useState<PointCloudQualityMode>('auto')
  const [waypoints, setWaypoints] = useState<NavWaypoint[]>([])
  const [addMode, setAddMode] = useState(false)
  const [activeDrawer, setActiveDrawer] = useState<'task' | 'map' | null>(null)
  const [infoOpen, setInfoOpen] = useState(false)
  const [followRobot, setFollowRobot] = useState(false)
  const [toolMode, setToolMode] = useState<'none' | 'obstacle' | 'pose'>('none')
  const [navigatingWaypointId, setNavigatingWaypointId] = useState<string | null>(null)
  const [estopSending, setEstopSending] = useState(false)
  const [restartLocalizationSending, setRestartLocalizationSending] = useState(false)
  const [radarChecking, setRadarChecking] = useState(false)
  const [rosbagLoading, setRosbagLoading] = useState(false)
  const [rosbagStatus, setRosbagStatus] = useState<RosbagRecordingResponse | null>(null)
  const [navAutoTrackEnabled, setNavAutoTrackEnabled] = useState(false)
  const [navAutoTrackLoading, setNavAutoTrackLoading] = useState(false)
  const [relocationPrompt, setRelocationPrompt] = useState<RelocationPromptState>({
    status: 'idle',
    message: '',
  })
  const [keyboardControlEnabled, setKeyboardControlEnabled] = useState(false)
  const [mouseMapPosition, setMouseMapPosition] = useState<{ x: number; y: number } | null>(null)
  const [logs, setLogs] = useState<LogItem[]>([])
  const [logsExpanded, setLogsExpanded] = useState(false)
  const [operationNotice, setOperationNotice] = useState<OperationNotice | null>(null)
  const operationNoticeTimerRef = useRef<number | null>(null)
  const [webglSupported, setWebglSupported] = useState(true)
  const [sceneDeleteConfirm, setSceneDeleteConfirm] = useState<PcdSceneItem | null>(null)
  // ── 高危操作确认 ──
  const [goToConfirm, setGoToConfirm] = useState<NavWaypoint | null>(null)
  const { telemetry } = useBotDogWebSocket()
  const navWs = useNavWebSocket()
  const { robotPose, globalPath, executionPath, localizationStatus, navigationStatus, setInitialState } = navWs
  const relocationNotice = getRelocationNotice(relocationPrompt)
  const waypointModeNotice = addMode
    ? { title: '3D ground 标点', message: '在 3D 蓝色 ground.pcd 上按住并拖动确定朝向。' }
    : null
  const poseModeNotice = toolMode === 'pose'
    ? { title: '重定位模式', message: '在 3D 蓝色 ground.pcd 上按住当前位置，拖动确定朝向。' }
    : null
  const localizationNotice = localizationStatus && localizationStatus.status !== 'ok'
    ? { title: '定位状态', message: summarizeLocalizationStatus(localizationStatus.status, localizationStatus.message) }
    : null
  const stateNotice = relocationNotice ?? waypointModeNotice ?? poseModeNotice ?? localizationNotice
  const stateNoticeKind = relocationPrompt.status !== 'idle'
    ? relocationPrompt.status === 'nav-waiting'
      ? 'waiting'
      : relocationPrompt.status === 'nav-ready'
        ? 'ready'
        : relocationPrompt.status
    : addMode || toolMode === 'pose'
      ? 'ready'
      : localizationNotice
        ? 'waiting'
        : 'idle'
  const currentNotice = operationNotice?.kind === 'error'
    ? operationNotice
    : stateNotice ?? operationNotice
  const currentNoticeKind = currentNotice === operationNotice
    ? operationNotice?.kind ?? 'idle'
    : stateNoticeKind
  const {
    startCommand,
    stopCommand,
    isControlling,
    currentCmd,
    lastResult,
    resultMessage,
  } = useRobotControl()

  const { linearSpeed, resetSpeeds: resetKeyboardSpeeds, turnSpeed } = useKeyboardRobotControl({
    canOperate,
    enabled: keyboardControlEnabled,
    isControlling,
    currentCmd,
    startCommand,
    stopCommand,
  })

  useEffect(() => {
    if (relocationPrompt.status === 'localized' && localizationStatus?.status === 'ok') {
      setRelocationPrompt({ status: 'idle', message: '' })
    }
  }, [localizationStatus?.status, relocationPrompt.status])

  const addLog = useCallback((message: string, level: LogItem['level'] = 'info') => {
    const timestamp = Date.now()
    setLogs((items) => [
      { id: timestamp + Math.random(), level, timestamp, message },
      ...items,
    ].slice(0, 30))

    setOperationNotice({
      title: level === 'error' ? '操作异常' : '操作反馈',
      message,
      kind: level,
    })
    if (operationNoticeTimerRef.current !== null) {
      window.clearTimeout(operationNoticeTimerRef.current)
    }
    operationNoticeTimerRef.current = window.setTimeout(() => {
      setOperationNotice(null)
      operationNoticeTimerRef.current = null
    }, level === 'error' ? 9000 : 5000)
  }, [])

  useEffect(() => () => {
    if (operationNoticeTimerRef.current !== null) {
      window.clearTimeout(operationNoticeTimerRef.current)
    }
  }, [])

  useEffect(() => {
    if (!canOperate) return
    let cancelled = false

    const syncNavAutoTrackMode = async () => {
      try {
        const result = await getNavAutoTrackMode()
        if (cancelled) return
        setNavAutoTrackEnabled(result.enabled)
      } catch (error) {
        if (!cancelled) {
          addLog(error instanceof Error ? error.message : '读取导航自动跟踪状态失败', 'error')
        }
      }
    }

    void syncNavAutoTrackMode()
    return () => {
      cancelled = true
    }
  }, [addLog, canOperate])

  useEffect(() => {
    if (!canOperate) {
      setRosbagStatus(null)
      return
    }

    let cancelled = false
    const syncRosbagStatus = async (reportError: boolean) => {
      try {
        const status = await getRosbagRecordingStatus()
        if (!cancelled) setRosbagStatus(status)
      } catch (error) {
        if (!cancelled && reportError) {
          addLog(error instanceof Error ? error.message : '读取录包状态失败', 'error')
        }
      }
    }

    void syncRosbagStatus(true)
    const timer = window.setInterval(() => void syncRosbagStatus(false), 2000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [addLog, canOperate])

  const formatRestartHealth = formatRestartHealthLog

  const handleSceneChanging = useCallback(() => {
    setAddMode(false)
    setInitialState({
      robotPose: null,
      globalPath: null,
      executionPath: null,
      localizationStatus: {
        status: 'initializing',
        frame_id: 'map',
        source: null,
        message: '场景已切换，等待重新定位',
        timestamp: Date.now() / 1000,
      },
    })
  }, [setInitialState])

  const {
    scenes,
    root,
    selectedSceneId,
    selectedSceneReady,
    selectedSceneNavigable,
    selectedSceneMessage,
    metadata,
    preview,
    tileManifest,
    loading,
    refreshScenes,
    selectScene,
    previewLayers,
    topDownLayers,
  } = useNavScenes({
    setInitialState,
    onWaypointsLoaded: setWaypoints,
    onLog: addLog,
    onSceneChanging: handleSceneChanging,
  })
  const sceneDisplayPointCount = useMemo(() => {
    if (!tileManifest) return null
    const tier = pointCloudQualityMode === 'performance'
      ? 'performance'
      : pointCloudQualityMode === 'quality'
        ? 'original'
        : 'balanced'
    return tileManifest.nodes.reduce((sum, node) => sum + node[tier].point_count, 0)
  }, [pointCloudQualityMode, tileManifest])
  const {
    closeMappingDialog,
    confirmStopMapping,
    handleConfirmStartMapping,
    handleToggleMapping,
    mappingActive,
    mappingDialogOpen,
    mappingPreflightChecking,
    mappingSceneError,
    mappingSceneName,
    mappingSaving,
    mappingSending,
    mappingSessionInfo,
    mappingStopConfirmOpen,
    setMappingSceneError,
    setMappingSceneName,
    setMappingStopConfirmOpen,
  } = useNavMappingControls({
    addLog,
    canOperate,
    refreshScenes,
  })
  const { mappingCloudPoints, liveMappingCloudPoints } = useMappingCloudWebSocket(mappingActive)

  useEffect(() => {
    setWebglSupported(detectWebGLSupport())
  }, [])

  const handleAddWaypoint = useCallback(async (pos: { x: number; y: number; z: number; yaw: number }) => {
    if (!selectedSceneId) return
    if (!selectedSceneNavigable) {
      addLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
      return
    }

    setAddMode(false)
    const defaultName = `巡检点${waypoints.length + 1}`
    const name = window.prompt('导航点名称', defaultName)?.trim()
    if (!name) {
      addLog('已退出标点，未保存导航点')
      return
    }

    const validatedName = validateWaypointName(name, waypoints.map((waypoint) => waypoint.name))
    if (!validatedName.ok) {
      addLog(validatedName.message, 'error')
      return
    }

    try {
      const created = await createWaypoint(selectedSceneId, {
        name: validatedName.value,
        x: pos.x,
        y: pos.y,
        z: pos.z,
        yaw: pos.yaw,
        frame_id: 'map',
      })
      const nextWaypoints = await listWaypoints(selectedSceneId)
      setWaypoints(nextWaypoints.items)
      addLog(
        `已保存导航点 ${validatedName.value}: x=${created.x.toFixed(3)}, y=${created.y.toFixed(3)}, z=${created.z.toFixed(3)}, yaw=${created.yaw.toFixed(3)}`,
      )
    } catch (error) {
      addLog(error instanceof Error ? error.message : '保存导航点失败', 'error')
    }
  }, [addLog, selectedSceneId, selectedSceneNavigable, waypoints])

  const handleSetPose = useCallback(async (pos: { x: number; y: number; z: number; yaw: number }) => {
    if (!selectedSceneId) return
    if (!canOperate || !selectedSceneNavigable) {
      addLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
      return
    }

    const payload: LocalizationPosePayload = {
      map_id: selectedSceneId,
      x: pos.x,
      y: pos.y,
      z: pos.z,
      yaw: pos.yaw,
      frame_id: 'map',
    }

    try {
      setInitialState({
        robotPose: null,
        globalPath: null,
        executionPath: null,
        localizationStatus: {
          status: 'initializing',
          frame_id: 'map',
          source: '/initialpose',
          message: '已发送重定位，等待 TF 恢复',
          timestamp: Date.now() / 1000,
        },
      })
      const pose = await setLocalizationPose(payload)
      setToolMode('none')
      setRelocationPrompt({
        status: 'nav-waiting',
        message: '重定位已发送，正在构建 global_planner 静态图；大场景首次加载可能需要 2–3 分钟。',
      })
      addLog(
        `已发送重定位: x=${pose.x.toFixed(3)}, y=${pose.y.toFixed(3)}, z=${pose.z.toFixed(3)}, yaw=${pose.yaw.toFixed(3)}`,
      )
      const ready = await waitNavigationRuntimeReady(600)
      setRelocationPrompt({
        status: 'nav-ready',
        message: ready.message || 'global_planner 已加载完成，导航和任务可用。',
      })
      addLog(ready.message || 'global_planner 已加载完成，导航和任务可用')
    } catch (error) {
      const message = error instanceof Error
        ? error.message
        : '设置重定位位姿失败'
      setRelocationPrompt({
        status: 'error',
        message,
      })
      addLog(message, 'error')
    }
  }, [
    addLog,
    canOperate,
    selectedSceneId,
    selectedSceneNavigable,
    setInitialState,
  ])

  const handleDeleteWaypoint = useCallback(async (waypointId: string) => {
    if (!selectedSceneId) return

    try {
      await deleteWaypoint(selectedSceneId, waypointId)
      const nextWaypoints = await listWaypoints(selectedSceneId)
      setWaypoints(nextWaypoints.items)
      addLog(`已删除导航点 ${waypointId}`)
    } catch (error) {
      addLog(error instanceof Error ? error.message : '删除导航点失败', 'error')
    }
  }, [addLog, selectedSceneId])

  // 中间层：拦截 go-to，先弹确认框
  const requestGoToWaypoint = useCallback((waypointId: string) => {
    if (!canOperate) return
    const waypoint = waypoints.find((item) => item.id === waypointId)
    if (!waypoint) return
    setGoToConfirm(waypoint)
  }, [canOperate, waypoints])

  const handleGoToWaypoint = useCallback(async (waypointId: string) => {
    if (!selectedSceneId) return
    if (!canOperate || !selectedSceneNavigable) {
      addLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
      return
    }

    setNavigatingWaypointId(waypointId)
    try {
      const result = await goToWaypoint(selectedSceneId, waypointId)
      const waypoint = waypoints.find((item) => item.id === waypointId)
      addLog(`已发布导航目标 ${waypoint?.name || waypointId} 到 ${result.topic}`)
    } catch (error) {
      addLog(error instanceof Error ? error.message : '发布导航目标失败', 'error')
    } finally {
      setNavigatingWaypointId(null)
    }
  }, [addLog, canOperate, selectedSceneId, selectedSceneNavigable, waypoints])

  const handleEmergencyStop = useCallback(async () => {
    if (!canOperate) return
    if (estopSending) return
    setEstopSending(true)
    try {
      const result = await triggerNavEmergencyStop()
      setNavigatingWaypointId(null)
      setInitialState({
        globalPath: null,
        executionPath: null,
        navigationStatus: {
          status: 'idle',
          target_waypoint_id: null,
          target_name: null,
          message: '已执行导航软停（全速度为 0）',
          timestamp: Date.now() / 1000,
        },
      })
      addLog(`已执行导航软停：${result.message}`, 'error')
    } catch (error) {
      addLog(error instanceof Error ? error.message : '执行导航软停失败', 'error')
    } finally {
      setEstopSending(false)
    }
  }, [addLog, canOperate, estopSending, setInitialState])

  const handleRestartNavigationLocalization = useCallback(async () => {
    if (!canOperate) return
    if (restartLocalizationSending) return

    if (!selectedSceneId || !selectedSceneNavigable) {
      addLog('当前场景缺少 ground.pcd，不能用于导航定位', 'error')
      return
    }

    setAddMode(false)
    setToolMode('none')
    setRestartLocalizationSending(true)
    setRelocationPrompt({
      status: 'restarting',
      message: '正在重启导航定位进程',
    })
    try {
      const result = await restartNavigationLocalization()
      if (!result.success || !result.running || !result.startup_ready) {
        throw new Error(result.message || '导航定位关键进程未就绪')
      }
      addLog(formatRestartHealth(result), result.navigation_ready || result.startup_ready ? 'info' : 'error')
      setRelocationPrompt({
        status: 'waiting',
        message: '正在等待 Super-LIO initialpose 接收状态',
      })
      addLog('导航定位进程已拉起，正在等待 Super-LIO initialpose 接收状态')

      const ready = await waitInitialposeReady(result.initialpose_wait_log_offset ?? 0, 60)
      setToolMode('pose')
      setRelocationPrompt({
        status: 'ready',
        message: ready.message,
      })
      addLog(`${ready.message}，已自动进入重定位标记模式`)
    } catch (error) {
      const message = error instanceof Error && error.name === 'AbortError'
        ? '重启导航定位请求超时，后端可能仍在执行，请查看 restart_navigation_localization.log'
        : error instanceof Error
          ? error.message
          : '重启导航定位失败'
      setRelocationPrompt({
        status: 'error',
        message,
      })
      addLog(message, 'error')
    } finally {
      setRestartLocalizationSending(false)
    }
  }, [addLog, canOperate, formatRestartHealth, restartLocalizationSending, selectedSceneId, selectedSceneNavigable])

  const requestDeleteScene = useCallback((scene: PcdSceneItem) => {
    setSceneDeleteConfirm(scene)
  }, [])

  const handleDeleteScene = useCallback(async () => {
    if (!sceneDeleteConfirm) return
    try {
      const result = await deletePcdScene(sceneDeleteConfirm.id)
      const removedTasks = result.cleanup?.tasks?.removed_count ?? 0
      const removedWaypoints = result.cleanup?.waypoints?.removed_items ?? 0
      addLog(`已删除场景文件夹 ${sceneDeleteConfirm.id}，清理导航点 ${removedWaypoints} 个，任务 ${removedTasks} 个`)
      setSceneDeleteConfirm(null)
      await refreshScenes()
    } catch (error) {
      addLog(error instanceof Error ? error.message : '删除场景失败', 'error')
    }
  }, [addLog, refreshScenes, sceneDeleteConfirm])

  const handleToolMode = useCallback((nextMode: 'obstacle' | 'pose') => {
    setToolMode((current) => {
      const resolved = current === nextMode ? 'none' : nextMode
      if (resolved !== 'none') {
        setAddMode(false)
      }
      addLog(
        resolved === 'none'
          ? '已退出工具模式'
          : resolved === 'obstacle'
            ? '已切换到添加障碍物模式'
            : '已切换到重定位模式，在地图上点选机器人当前位置',
      )
      return resolved
    })
  }, [addLog])

  const handleToggleFollowRobot = useCallback(() => {
    setFollowRobot((value) => {
      const nextValue = !value
      addLog(nextValue ? '已开启视角跟随' : '已关闭视角跟随')
      return nextValue
    })
  }, [addLog])

  const handleTogglePcdLayer = useCallback((layer: keyof PcdLayerVisibility) => {
    setPcdLayerVisibility((value) => ({ ...value, [layer]: !value[layer] }))
  }, [])

  const handleToggleKeyboardControl = useCallback(() => {
    if (keyboardControlEnabled) resetKeyboardSpeeds()
    setKeyboardControlEnabled((value) => !value)
  }, [keyboardControlEnabled, resetKeyboardSpeeds])

  const handleToggleWaypointMode = useCallback(() => {
    setAddMode((value) => {
      const nextValue = !value
      if (nextValue) {
        setToolMode('none')
      }
      addLog(nextValue ? '已切换到添加导航点模式' : '已退出标点')
      return nextValue
    })
  }, [addLog])
  const openTaskDrawer = useCallback(() => setActiveDrawer('task'), [])

  const pointCloudMode: 'none' | 'waypoint' | 'pose' =
    addMode ? 'waypoint' : (toolMode === 'pose' ? 'pose' : 'none')

  const {
    allLayers,
    displayedExecutionPath,
    displayedGlobalPath,
    groundCenterHeight,
    pointCloudViewKey,
    rightRailBounds,
    rightRailLayers,
    selectedSceneWaypoints,
  } = useNavPointCloudViewModel({
    executionPath,
    globalPath,
    liveMappingCloudPoints,
    mappingActive,
    mappingCloudPoints,
    mappingSessionInfo,
    metadata,
    pcdLayerVisibility,
    preview,
    previewLayers,
    topDownLayers,
    tileManifest,
    robotPose,
    selectedSceneId,
    waypoints,
  })

  const {
    creatingTask,
    draftSceneMessage,
    draftSceneNavigable,
    handleAddDraftStep,
    handleCancelCreateTask,
    handleCreateTask,
    handleDeleteTask,
    handleDraftStepChange,
    handleExecuteTask,
    handleRemoveDraftWaypoint,
    handleStartCreateTask,
    handleStartEditTask,
    handleStopSelectedTask,
    handleStopTask,
    handleTaskDraftChange,
    executingTaskId,
    selectedTaskId,
    setSelectedTaskId,
    taskDraft,
    taskEditorMode,
    tasks,
  } = useNavTasks({
    addLog,
    canOperate,
    openTaskDrawer,
    scenes,
    selectScene,
    selectedSceneId,
    selectedSceneNavigable,
    selectedSceneWaypoints,
    setInitialState,
    setNavigatingWaypointId,
  })

  const handleCheckRadar = useCallback(async () => {
    if (!canOperate) {
      addLog('当前无操作权限，无法检查雷达', 'error')
      return
    }
    if (radarChecking) return

    setRadarChecking(true)
    try {
      const result = await checkRadarHealth()
      const frequency = typeof result.frequency_hz === 'number' ? ` ${result.frequency_hz.toFixed(2)}Hz` : ''
      const topic = result.topic ? `${result.topic}${frequency}` : '未识别 topic'
      const level = result.level === 'normal' ? '正常' : result.level === 'warning' ? '警告' : '异常'
      addLog(`雷达${level}：${topic}；${result.message}`, result.ok ? 'info' : 'error')
    } catch (error) {
      addLog(error instanceof Error ? error.message : '雷达检查失败', 'error')
    } finally {
      setRadarChecking(false)
    }
  }, [addLog, canOperate, radarChecking])

  const handleToggleRosbag = useCallback(async () => {
    if (!canOperate) {
      addLog('当前无操作权限，无法控制录包', 'error')
      return
    }
    if (rosbagLoading) return

    const enabled = !rosbagStatus?.running
    setRosbagLoading(true)
    try {
      const result = await setRosbagRecordingEnabled(enabled)
      setRosbagStatus(result)
      addLog(result.message, result.saved === false ? 'error' : 'info')
    } catch (error) {
      addLog(error instanceof Error ? error.message : `${enabled ? '开始' : '停止'}录包失败`, 'error')
    } finally {
      setRosbagLoading(false)
    }
  }, [addLog, canOperate, rosbagLoading, rosbagStatus?.running])

  const handleToggleNavAutoTrack = useCallback(async () => {
    if (!canOperate) {
      addLog('当前无操作权限，无法切换导航自动跟踪', 'error')
      return
    }
    if (navAutoTrackLoading) return

    const nextEnabled = !navAutoTrackEnabled
    setNavAutoTrackLoading(true)
    try {
      const result = await setNavAutoTrackMode(nextEnabled)
      setNavAutoTrackEnabled(result.enabled)
      addLog(result.message)
    } catch (error) {
      addLog(error instanceof Error ? error.message : '切换导航自动跟踪失败', 'error')
    } finally {
      setNavAutoTrackLoading(false)
    }
  }, [addLog, canOperate, navAutoTrackEnabled, navAutoTrackLoading])

  return (
    <main className="pcd-demo-page">
      <NavPageHeader
        addMode={addMode}
        batteryPct={telemetry?.battery_pct}
        canOperate={canOperate}
        loading={loading}
        previewAvailable={Boolean(preview || tileManifest)}
        restartLocalizationSending={restartLocalizationSending}
        selectedSceneNavigable={selectedSceneNavigable}
        webglSupported={webglSupported}
        onRestartLocalization={() => void handleRestartNavigationLocalization()}
        onToggleWaypointMode={handleToggleWaypointMode}
      />

      <div className="pcd-workspace">
        <section className="pcd-main-stage">
          <div className="pcd-main-viewer">
            <NavMainViewer
              centerHeight={groundCenterHeight}
              followRobot={followRobot}
              executionPath={displayedExecutionPath}
              globalPath={displayedGlobalPath}
              layers={allLayers}
              mode={pointCloudMode}
              pointCloudQualityMode={pointCloudQualityMode}
              robotPose={robotPose}
              viewKey={pointCloudViewKey}
              wallColorMode={wallColorMode}
              tiledScene={mappingActive ? null : tileManifest}
              tileVisibility={{
                wall: pcdLayerVisibility.map,
                ground: pcdLayerVisibility.ground,
                footprint_fill: pcdLayerVisibility.footprint,
              }}
              waypoints={waypoints}
              webglSupported={webglSupported}
              onAddWaypoint={handleAddWaypoint}
              onGroundPointerChange={setMouseMapPosition}
              onSetPose={handleSetPose}
            />
          </div>
          <NavDrawerCluster
            activeDrawer={activeDrawer}
            canExecuteTask={canOperate}
            canSaveTask={draftSceneNavigable}
            canStartCreate={selectedSceneNavigable}
            canStopTask={canOperate && Boolean(selectedTaskId)}
            creatingTask={creatingTask}
            executingTaskId={executingTaskId}
            draft={taskDraft}
            navigationStatus={navigationStatus}
            root={root}
            scenes={scenes}
            scenesLoading={loading}
            selectedSceneId={selectedSceneId}
            selectedSceneMessage={draftSceneMessage}
            selectedSceneNavigable={draftSceneNavigable}
            selectedSceneWaypoints={selectedSceneWaypoints}
            selectedTaskId={selectedTaskId}
            taskEditorMode={taskEditorMode}
            tasks={tasks}
            onAddDraftStep={handleAddDraftStep}
            onCancelCreate={handleCancelCreateTask}
            onCreateTask={handleCreateTask}
            onDeleteScene={requestDeleteScene}
            onDeleteTask={handleDeleteTask}
            onDraftChange={handleTaskDraftChange}
            onDraftStepChange={handleDraftStepChange}
            onEditTask={handleStartEditTask}
            onExecuteTask={(taskId) => void handleExecuteTask(taskId)}
            onRefreshScenes={refreshScenes}
            onRemoveDraftWaypoint={handleRemoveDraftWaypoint}
            onSelectScene={selectScene}
            onSelectTask={setSelectedTaskId}
            onSetActiveDrawer={setActiveDrawer}
            onStartCreate={() => void handleStartCreateTask()}
            onStopTask={(taskId) => void handleStopTask(taskId)}
          />

          <SceneInfoDrawer
            open={infoOpen}
            metadata={metadata}
            sceneDisplayPointCount={sceneDisplayPointCount}
            mouseMapPosition={mouseMapPosition}
            robotPose={robotPose}
            selectedSceneReady={selectedSceneReady}
            selectedSceneNavigable={selectedSceneNavigable}
            selectedSceneMessage={selectedSceneMessage}
            localizationStatus={localizationStatus}
            onToggle={() => setInfoOpen((value) => !value)}
          />

          <NavToolStrip
            canOperate={canOperate}
            currentCmd={currentCmd}
            followRobot={followRobot}
            isControlling={isControlling}
            keyboardControlEnabled={keyboardControlEnabled}
            lastResultText={lastResult?.result ?? null}
            linearSpeed={linearSpeed}
            mappingActive={mappingActive}
            mappingPreflightChecking={mappingPreflightChecking}
            mappingSaving={mappingSaving}
            mappingSending={mappingSending}
            mappingSessionInfo={mappingSessionInfo}
            navAutoTrackEnabled={navAutoTrackEnabled}
            navAutoTrackLoading={navAutoTrackLoading}
            pcdLayerPanelOpen={pcdLayerPanelOpen}
            pcdLayerVisibility={pcdLayerVisibility}
            pointCloudQualityMode={pointCloudQualityMode}
            radarChecking={radarChecking}
            rosbagLoading={rosbagLoading}
            rosbagRunning={Boolean(rosbagStatus?.running)}
            rosbagUsesMappingLidar={rosbagStatus?.lidar_mode === 'mapping'}
            resultMessage={resultMessage}
            robotPoseAvailable={Boolean(robotPose)}
            selectedSceneNavigable={selectedSceneNavigable}
            selectedTaskId={selectedTaskId}
            toolMode={toolMode}
            turnSpeed={turnSpeed}
            webglSupported={webglSupported}
            wallColorMode={wallColorMode}
            onCheckRadar={() => void handleCheckRadar()}
            onToggleRosbag={() => void handleToggleRosbag()}
            onStopSelectedTask={handleStopSelectedTask}
            onToggleFollowRobot={handleToggleFollowRobot}
            onToggleKeyboardControl={handleToggleKeyboardControl}
            onToggleLayer={handleTogglePcdLayer}
            onToggleLayerPanel={() => setPcdLayerPanelOpen((value) => !value)}
            onSelectWallColorMode={setWallColorMode}
            onSelectPointCloudQualityMode={setPointCloudQualityMode}
            onToggleMapping={handleToggleMapping}
            onToggleNavAutoTrack={() => void handleToggleNavAutoTrack()}
            onToolMode={handleToolMode}
          />
        </section>

        <NavRightRail
          bounds={rightRailBounds}
          canOperate={canOperate}
          estopSending={estopSending}
          executionPath={displayedExecutionPath}
          globalPath={displayedGlobalPath}
          layers={rightRailLayers}
          navigatingWaypointId={navigatingWaypointId}
          robotPose={robotPose}
          sceneNavigable={selectedSceneNavigable}
          viewKey={pointCloudViewKey}
          waypoints={waypoints}
          onAddWaypoint={handleAddWaypoint}
          onDeleteWaypoint={handleDeleteWaypoint}
          onEmergencyStop={handleEmergencyStop}
          onGoToWaypoint={requestGoToWaypoint}
          onMouseMapPositionChange={setMouseMapPosition}
          onSetPose={handleSetPose}
        />

        <NavMessageCenter
          notice={currentNotice}
          noticeKind={currentNoticeKind}
          logs={logs}
          expanded={logsExpanded}
          onToggleExpanded={() => setLogsExpanded((value) => !value)}
        />
      </div>

      <SceneDeleteConfirmDialog
        scene={sceneDeleteConfirm}
        onCancel={() => setSceneDeleteConfirm(null)}
        onConfirm={() => void handleDeleteScene()}
      />
      <GoToWaypointConfirmDialog
        waypoint={goToConfirm}
        onCancel={() => setGoToConfirm(null)}
        onConfirm={(waypoint) => {
          setGoToConfirm(null)
          void handleGoToWaypoint(waypoint.id)
        }}
      />
      <MappingStartDialog
        open={mappingDialogOpen}
        sceneName={mappingSceneName}
        error={mappingSceneError}
        preflightChecking={mappingPreflightChecking}
        sending={mappingSending}
        onSceneNameChange={setMappingSceneName}
        onClearError={() => setMappingSceneError(null)}
        onCancel={closeMappingDialog}
        onConfirm={() => void handleConfirmStartMapping()}
      />
      <MappingStopConfirmDialog
        open={mappingStopConfirmOpen}
        minRuntimeSeconds={MIN_MAPPING_RUNTIME_SECONDS}
        onCancel={() => setMappingStopConfirmOpen(false)}
        onConfirm={confirmStopMapping}
      />
    </main>
  )
}
