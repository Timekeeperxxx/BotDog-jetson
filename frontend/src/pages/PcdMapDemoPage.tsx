import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  Boxes,
  ChevronDown,
  ChevronUp,
  Crosshair,
  Keyboard,
  Loader2,
  LocateFixed,
  Radar,
  Square,
} from 'lucide-react'
import {
  createWaypoint,
  deleteWaypoint,
  goToWaypoint,
  listNavTasks,
  listWaypoints,
  deletePcdScene,
  deleteNavTask,
  executeNavTask,
  checkRadarHealth,
  getMappingStatus,
  saveNavTask,
  stopNavTask,
  restartNavigationLocalization,
  setMappingEnabled,
  setLocalizationPose,
  triggerNavEmergencyStop,
  waitInitialposeReady,
  waitNavigationRuntimeReady,
} from '../api/pcdMapApi'
import { NavWaypointPanel } from '../components/pcd/NavWaypointPanel'
import { PcdFileListPanel } from '../components/pcd/PcdFileListPanel'
import { PointCloud3DViewer } from '../components/pcd/PointCloud3DViewer'
import { PointCloudTopDownCanvas } from '../components/pcd/PointCloudTopDownCanvas'
import { detectWebGLSupport } from '../components/pcd/webglSupport'
import { TaskCreatorDrawer } from '../components/pcd/TaskCreatorDrawer'
import { TaskDrawerPanel } from '../components/pcd/TaskDrawerPanel'
import { useRobotControl } from '../hooks/useRobotControl'
import { useNavWebSocket } from '../hooks/useNavWebSocket'
import { useMappingCloudWebSocket } from '../hooks/useMappingCloudWebSocket'
import { hasAuthSession, hasRole, useAuthState } from '../stores/authStore'
import type { LocalizationPosePayload, NavWaypoint, PcdBounds, PcdSceneItem } from '../types/pcdMap'
import type { TaskDefinition, TaskDraft, TaskDraftStep } from '../types/taskWorkflow'
import { validateWaypointName } from '../utils/navWaypointValidation'
import { useNavScenes } from './nav/useNavScenes'
import {
  buildTaskDraftFromTask,
  buildTaskDefinitionFromDraft,
  applyTaskDraftPatch,
  appendTaskDraftStep,
  findSceneById,
  findTaskById,
  emptyTaskDraft,
  formatRestartHealthLog,
  nowText,
  resolveRobotCommandFromKey,
  resolveInitialTaskMapId,
  resolveTaskSceneId,
  insertTaskDraftStep,
  patchTaskDraftStep,
  removeTaskDraftStep,
  taskContainsPostureControl,
  validateMappingSceneName,
} from './nav/navPageUtils'

type LogItem = {
  id: number
  level: 'info' | 'error'
  message: string
}

type MappingSessionInfo = {
  sceneName: string
  mapDir: string
}

type RelocationPromptState =
  | { status: 'idle'; message: string }
  | { status: 'restarting' | 'waiting' | 'ready' | 'localized' | 'nav-waiting' | 'nav-ready' | 'error'; message: string }

const DEFAULT_LINEAR_SPEED = 0.3
const DEFAULT_TURN_SPEED = 0.5
const SPEED_STEP = 0.1
const MAX_LINEAR_SPEED = 0.6
const MAX_TURN_SPEED = 0.8

function clampSpeed(value: number, limit: number) {
  return Math.max(0, Math.min(limit, Number(value.toFixed(1))))
}

function isArrowSpeedKey(key: string) {
  return ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(key)
}

function formatSpeed(value: number) {
  return value.toFixed(1)
}

function compactRuntimeMessage(message: string) {
  if (message.includes('relocation 进程未运行')) {
    return 'Super-LIO 已退出，请重新重启导航定位。'
  }
  if (message.includes('/initialpose 暂无订阅者')) {
    return '还没有接收端，请稍后或重新重启导航定位。'
  }
  if (message.includes('target_frame does not exist') || message.includes('map') && message.includes('TF')) {
    return '等待 map TF 恢复。'
  }
  if (message.includes('超时')) {
    return '等待超时，请查看日志后重试。'
  }
  return message.length > 56 ? `${message.slice(0, 56)}...` : message
}

function getRelocationNotice(prompt: RelocationPromptState) {
  switch (prompt.status) {
    case 'restarting':
      return { title: '正在重启定位', message: '请稍候，暂时不要标点。' }
    case 'waiting':
      return { title: '等待 Super-LIO', message: '正在确认重定位接收端。' }
    case 'ready':
      return { title: '现在标记重定位点', message: '在 3D 蓝色 ground.pcd 上按住当前位置，拖动确定朝向。' }
    case 'localized':
      return { title: '重定位已发送', message: '正在等待位姿恢复。' }
    case 'nav-waiting':
      return { title: '导航控制链路恢复中', message: compactRuntimeMessage(prompt.message) }
    case 'nav-ready':
      return { title: '导航和任务可用', message: prompt.message || 'global_planner 已加载完成。' }
    case 'error':
      return { title: '重定位未就绪', message: compactRuntimeMessage(prompt.message) }
    case 'idle':
      return null
  }
}

function summarizeLocalizationStatus(status: string, message: string) {
  if (status === 'ok') return message
  return compactRuntimeMessage(message)
}

export function PcdMapDemoPage() {
  useAuthState()
  const canOperate = hasAuthSession() && hasRole('operator')
  const previewPointLimit = 100000
  const [waypoints, setWaypoints] = useState<NavWaypoint[]>([])
  const [addMode, setAddMode] = useState(false)
  const [tasks, setTasks] = useState<TaskDefinition[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [creatingTask, setCreatingTask] = useState(false)
  const [taskEditorMode, setTaskEditorMode] = useState<'create' | 'edit' | null>(null)
  const [taskDraft, setTaskDraft] = useState<TaskDraft>(emptyTaskDraft)
  const [activeDrawer, setActiveDrawer] = useState<'task' | 'map' | null>(null)
  const [infoOpen, setInfoOpen] = useState(true)
  const [followRobot, setFollowRobot] = useState(false)
  const [toolMode, setToolMode] = useState<'none' | 'obstacle' | 'pose'>('none')
  const [navigatingWaypointId, setNavigatingWaypointId] = useState<string | null>(null)
  const [estopSending, setEstopSending] = useState(false)
  const [restartLocalizationSending, setRestartLocalizationSending] = useState(false)
  const [mappingActive, setMappingActive] = useState(false)
  const [mappingSending, setMappingSending] = useState(false)
  const [mappingDialogOpen, setMappingDialogOpen] = useState(false)
  const [mappingSceneName, setMappingSceneName] = useState('')
  const [mappingSceneError, setMappingSceneError] = useState<string | null>(null)
  const [mappingSessionInfo, setMappingSessionInfo] = useState<MappingSessionInfo | null>(null)
  const [radarChecking, setRadarChecking] = useState(false)
  const [relocationPrompt, setRelocationPrompt] = useState<RelocationPromptState>({
    status: 'idle',
    message: '',
  })
  const [mappingStartTime, setMappingStartTime] = useState<number | null>(null)
  const [mappingStopConfirmOpen, setMappingStopConfirmOpen] = useState(false)
  const [keyboardControlEnabled, setKeyboardControlEnabled] = useState(false)
  const [linearSpeed, setLinearSpeed] = useState(DEFAULT_LINEAR_SPEED)
  const [turnSpeed, setTurnSpeed] = useState(DEFAULT_TURN_SPEED)
  const [mouseMapPosition, setMouseMapPosition] = useState<{ x: number; y: number } | null>(null)
  const [logs, setLogs] = useState<LogItem[]>([])
  const [logsExpanded, setLogsExpanded] = useState(false)
  const [webglSupported, setWebglSupported] = useState(true)
  const [sceneDeleteConfirm, setSceneDeleteConfirm] = useState<PcdSceneItem | null>(null)
  // ── 高危操作确认 ──
  const [goToConfirm, setGoToConfirm] = useState<NavWaypoint | null>(null)
  const navWs = useNavWebSocket()
  const { robotPose, globalPath, localizationStatus, navigationStatus, setInitialState } = navWs
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
  const currentNotice = relocationNotice ?? waypointModeNotice ?? poseModeNotice ?? localizationNotice
  const currentNoticeKind = relocationPrompt.status !== 'idle'
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
  const latestLog = logs[0] ?? null
  const { mappingCloudPoints, liveMappingCloudPoints, clearMappingCloud } = useMappingCloudWebSocket(mappingActive)
  const {
    startCommand,
    stopCommand,
    isControlling,
    currentCmd,
    lastResult,
    resultMessage,
  } = useRobotControl()

  const prevMappingActiveRef = useRef(mappingActive)
  const linearSpeedRef = useRef(DEFAULT_LINEAR_SPEED)
  const turnSpeedRef = useRef(DEFAULT_TURN_SPEED)
  useEffect(() => {
    if (prevMappingActiveRef.current !== mappingActive) {
      prevMappingActiveRef.current = mappingActive
      clearMappingCloud()
    }
  }, [mappingActive, clearMappingCloud])

  useEffect(() => {
    if (relocationPrompt.status === 'localized' && localizationStatus?.status === 'ok') {
      setRelocationPrompt({ status: 'idle', message: '' })
    }
  }, [localizationStatus?.status, relocationPrompt.status])

  const addLog = useCallback((message: string, level: LogItem['level'] = 'info') => {
    setLogs((items) => [
      { id: Date.now() + Math.random(), level, message: `${nowText()} ${message}` },
      ...items,
    ].slice(0, 30))
  }, [])

  useEffect(() => {
    if (!canOperate) return
    let cancelled = false

    const syncMappingStatus = async () => {
      try {
        const status = await getMappingStatus()
        if (cancelled) return
        if (!status.running) {
          return
        }

        setMappingActive(true)
        setMappingSessionInfo({
          sceneName: status.scene_name || '未命名场景',
          mapDir: status.map_dir || '',
        })
        setMappingStartTime(status.started_at ? status.started_at * 1000 : Date.now())
        addLog(status.message || '检测到后端建图正在运行，已恢复实时点云预览')
      } catch (error) {
        if (!cancelled) {
          addLog(error instanceof Error ? error.message : '读取建图状态失败', 'error')
        }
      }
    }

    void syncMappingStatus()
    return () => {
      cancelled = true
    }
  }, [addLog, canOperate])

  const formatRestartHealth = formatRestartHealthLog

  const handleSceneChanging = useCallback(() => {
    setAddMode(false)
    setInitialState({
      robotPose: null,
      globalPath: null,
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
    loading,
    refreshScenes,
    selectScene,
    previewLayers,
  } = useNavScenes({
    previewPointLimit,
    setInitialState,
    onWaypointsLoaded: setWaypoints,
    onLog: addLog,
    onSceneChanging: handleSceneChanging,
  })

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
        message: '重定位已发送，正在等待 global_planner 和导航控制链路恢复。',
      })
      addLog(
        `已发送重定位: x=${pose.x.toFixed(3)}, y=${pose.y.toFixed(3)}, z=${pose.z.toFixed(3)}, yaw=${pose.yaw.toFixed(3)}`,
      )
      const ready = await waitNavigationRuntimeReady(60)
      setRelocationPrompt({
        status: 'nav-ready',
        message: ready.message || 'global_planner 已加载完成，导航和任务可用。',
      })
      addLog(ready.message || 'global_planner 已加载完成，导航和任务可用')
    } catch (error) {
      addLog(
        error instanceof Error
          ? error.message
          : '设置重定位位姿失败',
        'error',
      )
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
        navigationStatus: {
          status: 'idle',
          target_waypoint_id: null,
          target_name: null,
          message: '已执行导航急停',
          timestamp: Date.now() / 1000,
        },
      })
      addLog(`已执行导航急停：${result.message}`, 'error')
    } catch (error) {
      addLog(error instanceof Error ? error.message : '执行导航急停失败', 'error')
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
      addLog(formatRestartHealth(result), result.navigation_ready ? 'info' : 'error')
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
      await deletePcdScene(sceneDeleteConfirm.id)
      addLog(`已删除场景文件夹 ${sceneDeleteConfirm.id}`)
      setSceneDeleteConfirm(null)
      await refreshScenes()
    } catch (error) {
      addLog(error instanceof Error ? error.message : '删除场景失败', 'error')
    }
  }, [addLog, refreshScenes, sceneDeleteConfirm])

  const MIN_MAPPING_RUNTIME_SECONDS = 90

  const handleStopMapping = useCallback(async () => {
    if (!canOperate) return
    if (mappingSending) return

    // 建图时间过短时弹出确认
    if (mappingStartTime != null) {
      const elapsed = (Date.now() - mappingStartTime) / 1000
      if (elapsed < MIN_MAPPING_RUNTIME_SECONDS) {
        setMappingStopConfirmOpen(true)
        return
      }
    }

    setMappingStopConfirmOpen(false)
    setMappingSending(true)
    try {
      const result = await setMappingEnabled(false)
      setMappingActive(false)
      setMappingSessionInfo(null)
      setMappingStartTime(null)

      if (result.saved) {
        addLog(result.message || '地图已保存')
        // 等一小会儿让文件系统同步，再刷新场景列表
        setTimeout(() => {
          void refreshScenes()
        }, 500)
      } else {
        const missing: string[] = []
        if (result.map_pcd_candidates.length === 0) missing.push('map.pcd')
        if (result.ground_pcd_candidates.length === 0) missing.push('ground.pcd')
        addLog(
          `地图保存不完整：缺少 ${missing.join('、')}，请查看 start_mapping_debug.log`,
          'error',
        )
      }
    } catch (error) {
      addLog(error instanceof Error ? error.message : '停止建图失败', 'error')
    } finally {
      setMappingSending(false)
    }
  }, [addLog, canOperate, mappingSending, mappingStartTime, refreshScenes])

  const handleOpenMappingDialog = useCallback(() => {
    if (!canOperate) return
    if (mappingSending) return
    setMappingSceneError(null)
    setMappingSceneName('')
    setMappingDialogOpen(true)
  }, [canOperate, mappingSending])

  const handleConfirmStartMapping = useCallback(async () => {
    if (!canOperate) return
    if (mappingSending) return

    const validated = validateMappingSceneName(mappingSceneName)
    if (!validated.ok) {
      setMappingSceneError(validated.message)
      return
    }

    setMappingSceneError(null)
    setMappingSending(true)
    try {
      const result = await setMappingEnabled(true, validated.value)
      setMappingActive(true)
      setMappingStartTime(Date.now())
      setMappingSessionInfo({
        sceneName: result.scene_name || validated.value,
        mapDir: result.map_dir || '',
      })
      setMappingDialogOpen(false)
      addLog(
        result.message
          ? `${result.message}：${result.scene_name}，目录=${result.map_dir}`
          : `建图已启动：${result.scene_name}，目录=${result.map_dir}`,
      )
    } catch (error) {
      const message = error instanceof Error ? error.message : '启动建图失败'
      addLog(message, 'error')
      if (message.includes('建图已在进行中')) {
        setMappingActive(true)
      }
    } finally {
      setMappingSending(false)
    }
  }, [addLog, canOperate, mappingSceneName, mappingSending])

  const refreshTasks = useCallback(async () => {
    try {
      const data = await listNavTasks()
      setTasks(Array.isArray(data.items) ? data.items : [])
    } catch (error) {
      addLog(error instanceof Error ? error.message : '任务工作流读取失败', 'error')
    }
  }, [addLog])

  useEffect(() => {
    void refreshTasks()
  }, [refreshTasks])

  useEffect(() => {
    if (!selectedTaskId && tasks.length > 0) {
      setSelectedTaskId(tasks[0].id)
    }
    if (selectedTaskId && !tasks.some((task) => task.id === selectedTaskId)) {
      setSelectedTaskId(tasks[0]?.id ?? null)
    }
  }, [selectedTaskId, tasks])

  const resetKeyboardSpeeds = useCallback(() => {
    linearSpeedRef.current = DEFAULT_LINEAR_SPEED
    turnSpeedRef.current = DEFAULT_TURN_SPEED
    setLinearSpeed(DEFAULT_LINEAR_SPEED)
    setTurnSpeed(DEFAULT_TURN_SPEED)
  }, [])

  const adjustKeyboardSpeed = useCallback((key: string) => {
    let nextLinearSpeed = linearSpeedRef.current
    let nextTurnSpeed = turnSpeedRef.current

    if (key === 'ArrowUp') {
      nextLinearSpeed = clampSpeed(nextLinearSpeed + SPEED_STEP, MAX_LINEAR_SPEED)
    } else if (key === 'ArrowDown') {
      nextLinearSpeed = clampSpeed(nextLinearSpeed - SPEED_STEP, MAX_LINEAR_SPEED)
    } else if (key === 'ArrowLeft') {
      nextTurnSpeed = clampSpeed(nextTurnSpeed + SPEED_STEP, MAX_TURN_SPEED)
    } else if (key === 'ArrowRight') {
      nextTurnSpeed = clampSpeed(nextTurnSpeed - SPEED_STEP, MAX_TURN_SPEED)
    }

    linearSpeedRef.current = nextLinearSpeed
    turnSpeedRef.current = nextTurnSpeed
    setLinearSpeed(nextLinearSpeed)
    setTurnSpeed(nextTurnSpeed)
  }, [])

  const startKeyboardCommand = useCallback((cmd: ReturnType<typeof resolveRobotCommandFromKey>) => {
    if (!cmd) return

    if (cmd === 'forward' || cmd === 'backward') {
      const vx = linearSpeedRef.current
      if (vx === 0) return
      startCommand(cmd, { vx })
      return
    }

    if (cmd === 'left' || cmd === 'right') {
      const vyaw = turnSpeedRef.current
      if (vyaw === 0) return
      startCommand(cmd, { vyaw })
      return
    }

    startCommand(cmd)
  }, [startCommand])

  useEffect(() => {
    if (!keyboardControlEnabled) {
      resetKeyboardSpeeds()
      if (isControlling) stopCommand()
    }
  }, [keyboardControlEnabled, isControlling, resetKeyboardSpeeds, stopCommand])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((event.target as HTMLElement).tagName)) return
      if (event.repeat) return
      if (!canOperate || !keyboardControlEnabled) return

      if (isArrowSpeedKey(event.key)) {
        event.preventDefault()
        adjustKeyboardSpeed(event.key)
        return
      }

      const cmd = resolveRobotCommandFromKey(event.key)

      if (cmd) {
        event.preventDefault()
        startKeyboardCommand(cmd)
      }
    }

    const handleKeyUp = (event: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((event.target as HTMLElement).tagName)) return
      if (isArrowSpeedKey(event.key)) {
        event.preventDefault()
        return
      }

      const cmd = resolveRobotCommandFromKey(event.key)

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
  }, [adjustKeyboardSpeed, canOperate, keyboardControlEnabled, currentCmd, startKeyboardCommand, stopCommand])

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

  const pointCloudMode: 'none' | 'waypoint' | 'pose' =
    addMode ? 'waypoint' : (toolMode === 'pose' ? 'pose' : 'none')

  const selectedTask = useMemo(
    () => findTaskById(tasks, selectedTaskId),
    [selectedTaskId, tasks],
  )

  const selectedTaskScene = useMemo(
    () => findSceneById(scenes, selectedTask ? resolveTaskSceneId(selectedTask) : null),
    [scenes, selectedTask],
  )
  const selectedTaskSceneNavigable = selectedTaskScene?.navigable ?? false

  const allLayers = useMemo(() => {
    if (!mappingActive) return previewLayers ?? []
    if (mappingCloudPoints.length === 0 && liveMappingCloudPoints.length === 0) return []
    const layers = []
    if (mappingCloudPoints.length > 0) {
      layers.push({ role: 'mapping' as const, points: mappingCloudPoints })
    }
    if (liveMappingCloudPoints.length > 0) {
      layers.push({ role: 'live' as const, points: liveMappingCloudPoints })
    }
    return layers
  }, [previewLayers, mappingActive, mappingCloudPoints, liveMappingCloudPoints])
  const pointCloudViewKey = mappingActive
    ? `mapping:${mappingSessionInfo?.sceneName || mappingSessionInfo?.mapDir || 'active'}`
    : `scene:${selectedSceneId || 'none'}`

  const liveMappingBounds = useMemo<PcdBounds | null>(() => {
    if (!mappingActive || (mappingCloudPoints.length === 0 && liveMappingCloudPoints.length === 0)) return null

    let minX = Number.POSITIVE_INFINITY
    let maxX = Number.NEGATIVE_INFINITY
    let minY = Number.POSITIVE_INFINITY
    let maxY = Number.NEGATIVE_INFINITY
    let minZ = Number.POSITIVE_INFINITY
    let maxZ = Number.NEGATIVE_INFINITY

    const updateBounds = ([x, y, z]: [number, number, number]) => {
      minX = Math.min(minX, x)
      maxX = Math.max(maxX, x)
      minY = Math.min(minY, y)
      maxY = Math.max(maxY, y)
      minZ = Math.min(minZ, z)
      maxZ = Math.max(maxZ, z)
    }

    mappingCloudPoints.forEach(updateBounds)
    liveMappingCloudPoints.forEach(updateBounds)

    return {
      min_x: minX,
      max_x: maxX,
      min_y: minY,
      max_y: maxY,
      min_z: minZ,
      max_z: maxZ,
    }
  }, [mappingActive, mappingCloudPoints, liveMappingCloudPoints])

  const groundCenterHeight = useMemo(() => {
    const bounds = preview?.layers.ground?.bounds ?? metadata?.files.ground?.bounds ?? null
    return bounds ? (bounds.min_z + bounds.max_z) / 2 : null
  }, [metadata?.files.ground?.bounds, preview?.layers.ground?.bounds])

  const mapOptions = useMemo(
    () => scenes.map((scene) => ({ id: scene.id, name: scene.name })),
    [scenes],
  )

  const selectedSceneWaypoints = useMemo(
    () => waypoints.map((waypoint) => ({ id: waypoint.id, name: waypoint.name })),
    [waypoints],
  )

  const draftScene = useMemo(
    () => findSceneById(scenes, taskDraft.mapId),
    [scenes, taskDraft.mapId],
  )
  const draftSceneNavigable = draftScene?.navigable ?? false
  const draftSceneMessage = draftScene?.message ?? null

  const handleTaskDraftChange = useCallback((patch: Partial<TaskDraft>) => {
    setTaskDraft((current) => applyTaskDraftPatch(current, patch))
    if (patch.mapId && patch.mapId !== selectedSceneId) {
      void selectScene(patch.mapId)
    }
  }, [selectedSceneId, selectScene])

  const handleAddDraftStep = useCallback((index?: number) => {
    setTaskDraft((current) => (
      typeof index === 'number'
        ? insertTaskDraftStep(current, index)
        : appendTaskDraftStep(current)
    ))
  }, [])

  const handleRemoveDraftWaypoint = useCallback((index: number) => {
    setTaskDraft((current) => removeTaskDraftStep(current, index))
  }, [])

  const handleDraftStepChange = useCallback((index: number, patch: Partial<TaskDraftStep>) => {
    setTaskDraft((current) => patchTaskDraftStep(current, index, patch))
  }, [])

  const handleStartCreateTask = useCallback(async () => {
    if (!selectedSceneNavigable) {
      addLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
      return
    }

    setTaskDraft({
      ...emptyTaskDraft,
      mapId: resolveInitialTaskMapId(selectedSceneId, scenes.map((scene) => scene.id)),
    })
    setCreatingTask(true)
    setTaskEditorMode('create')
    setActiveDrawer('task')
  }, [addLog, scenes, selectedSceneId, selectedSceneNavigable])

  const handleStartEditTask = useCallback((taskId: string) => {
    const task = findTaskById(tasks, taskId)
    if (!task) return
    const nextDraft: TaskDraft = buildTaskDraftFromTask(task)
    setSelectedTaskId(task.id)
    setTaskDraft(nextDraft)
    setCreatingTask(true)
    setTaskEditorMode('edit')
    setActiveDrawer('task')
    if (task.mapId !== selectedSceneId) {
      void selectScene(task.mapId)
    }
  }, [selectedSceneId, selectScene, tasks])

  const handleCancelCreateTask = useCallback(() => {
    setCreatingTask(false)
    setTaskEditorMode(null)
    setTaskDraft(emptyTaskDraft)
  }, [])

  const handleCreateTask = useCallback(async () => {
    const result = buildTaskDefinitionFromDraft({
      draft: taskDraft,
      scenes,
      waypoints: selectedSceneWaypoints,
      tasks,
      taskEditorMode,
      selectedTaskId,
    })
    if (!result.ok) {
      addLog(result.message, 'error')
      return
    }

    const nextTask = result.task
    const name = nextTask.name

    try {
      await saveNavTask(nextTask)
    } catch (error) {
      addLog(error instanceof Error ? error.message : '保存任务失败', 'error')
      return
    }

    const nextTasks =
      taskEditorMode === 'edit' && selectedTaskId
        ? tasks.map((item) => (item.id === selectedTaskId ? nextTask : item))
        : [nextTask, ...tasks]
    setTasks(nextTasks)
    setSelectedTaskId(nextTask.id)
    setCreatingTask(false)
    setTaskEditorMode(null)
    setTaskDraft(emptyTaskDraft)
    setActiveDrawer('task')
    addLog(taskEditorMode === 'edit' ? `已更新任务 ${name}` : `已创建任务工作流 ${name}`)
  }, [addLog, scenes, selectedSceneWaypoints, selectedTaskId, taskDraft, taskEditorMode, tasks])

  const handleDeleteTask = useCallback(async (taskId: string) => {
    const task = findTaskById(tasks, taskId)
    if (!task) return
    try {
      await deleteNavTask(task.id)
    } catch (error) {
      addLog(error instanceof Error ? error.message : '删除任务失败', 'error')
      return
    }
    const nextTasks = tasks.filter((item) => item.id !== task.id)
    setTasks(nextTasks)
    addLog(`已删除任务 ${task.name}`)
  }, [addLog, tasks])

  const handleExecuteTask = useCallback(async (taskId: string) => {
    if (!canOperate) {
      addLog('当前无操作权限，无法执行任务', 'error')
      return
    }

    const task = findTaskById(tasks, taskId)
    if (!task) return
    setSelectedTaskId(task.id)
    const taskScene = findSceneById(scenes, task.mapId)
    if (!taskScene) {
      addLog('任务关联场景不存在', 'error')
      return
    }
    if (!taskScene.navigable) {
      addLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
      return
    }
    if (taskContainsPostureControl(task)) {
      addLog('当前任务包含姿态控制步骤，姿态控制仅完成前端配置，暂未接入后端执行。', 'error')
      return
    }
    if (task.mapId !== selectedSceneId) {
      await selectScene(task.mapId)
    }
    try {
      const result = await executeNavTask(task.id)
      setNavigatingWaypointId(null)
      setInitialState({
        navigationStatus: {
          status: 'navigating',
          target_waypoint_id: null,
          target_name: task.name,
          task_id: task.id,
          message: result.message,
          timestamp: Date.now() / 1000,
        },
      })
      addLog(`已执行导航任务 ${task.name}，已发布 ${result.topic}=true`)
    } catch (error) {
      addLog(error instanceof Error ? error.message : '执行导航任务失败', 'error')
    }
  }, [addLog, canOperate, scenes, selectedSceneId, selectScene, setInitialState, tasks])

  const handleStopTask = useCallback(async (taskId: string) => {
    if (!canOperate) {
      addLog('当前无操作权限，无法停止任务', 'error')
      return
    }

    const task = findTaskById(tasks, taskId)
    if (!task) return

    try {
      const result = await stopNavTask(task.id)
      setNavigatingWaypointId(null)
      setInitialState({
        globalPath: null,
        navigationStatus: {
          status: 'idle',
          target_waypoint_id: null,
          target_name: null,
          message: result.message,
          timestamp: Date.now() / 1000,
        },
      })
      addLog(`已停止导航任务 ${task.name}，已发布 ${result.topic}=false`)
    } catch (error) {
      addLog(error instanceof Error ? error.message : '停止导航任务失败', 'error')
    }
  }, [addLog, canOperate, setInitialState, tasks])

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

  return (
    <main className="pcd-demo-page">
      <header className="pcd-demo-header">
        <div className="pcd-title-row">
          <div className="pcd-title-block">
            <h1>BotDog 导航巡逻</h1>
            <p>from 西部泰力</p>
          </div>
        </div>
        <div className="pcd-header-actions">
          {loading ? (
            <span className="pcd-loading">
              <Loader2 size={16} /> 加载中
            </span>
          ) : null}
          <button
            className="pcd-secondary-button"
            disabled={!canOperate || restartLocalizationSending || !selectedSceneNavigable || !webglSupported}
            onClick={() => void handleRestartNavigationLocalization()}
            title={!webglSupported ? '当前浏览器无法使用 3D 点云标记' : !selectedSceneNavigable ? '当前场景缺少 ground.pcd' : undefined}
          >
            {restartLocalizationSending ? '重启中...' : '重启导航定位'}
          </button>
          <button
            className={`pcd-primary-button ${addMode ? 'is-active' : ''}`}
            disabled={!preview || !selectedSceneNavigable || !webglSupported}
            onClick={handleToggleWaypointMode}
            title={!webglSupported ? '当前浏览器无法使用 3D 点云标记' : !selectedSceneNavigable ? '当前场景缺少 ground.pcd' : undefined}
          >
            <Crosshair size={16} />
            {addMode ? '退出标点' : '添加导航点'}
          </button>
        </div>
      </header>

      <div className="pcd-workspace">
        <section className="pcd-main-stage">
          <div className="pcd-main-viewer">
            {webglSupported ? (
              <PointCloud3DViewer
                layers={allLayers}
                viewKey={pointCloudViewKey}
                waypoints={waypoints}
                robotPose={robotPose}
                globalPath={globalPath}
                mode={pointCloudMode}
                followRobot={followRobot}
                centerHeight={groundCenterHeight}
                onGroundPointerChange={setMouseMapPosition}
                onAddWaypoint={handleAddWaypoint}
                onSetPose={handleSetPose}
              />
            ) : (
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
            )}
          </div>
          <div className="pcd-drawer-cluster">
            <div className="pcd-drawer-rail">
              <button
                className={`pcd-drawer-toggle ${activeDrawer === 'task' ? 'is-active' : ''}`}
                onClick={() => {
                  const next = activeDrawer === 'task' ? null : 'task'
                  setActiveDrawer(next)
                }}
                title={activeDrawer === 'task' ? '收起任务选择' : '展开任务选择'}
              >
                <span>任务选择</span>
              </button>
              <button
                className={`pcd-drawer-toggle ${activeDrawer === 'map' ? 'is-active' : ''}`}
                onClick={() => {
                  const next = activeDrawer === 'map' ? null : 'map'
                  setActiveDrawer(next)
                }}
                title={activeDrawer === 'map' ? '收起场景选择' : '展开场景选择'}
              >
                <span>场景选择</span>
              </button>
            </div>
            <div className={`pcd-drawer-body pcd-shared-drawer-body ${activeDrawer ? 'is-open' : 'is-closed'}`}>
              {activeDrawer === 'task' ? (
                <TaskDrawerPanel
                  tasks={tasks}
                  selectedTaskId={selectedTaskId}
                  navigationStatus={navigationStatus}
                  canStartCreate={selectedSceneNavigable}
                  canExecuteTask={canOperate && selectedTaskSceneNavigable}
                  canStopTask={canOperate && Boolean(selectedTaskId)}
                  onSelectTask={setSelectedTaskId}
                  onEditTask={handleStartEditTask}
                  onExecuteTask={(taskId) => void handleExecuteTask(taskId)}
                  onStopTask={(taskId) => void handleStopTask(taskId)}
                  onDeleteTask={handleDeleteTask}
                  onStartCreate={() => void handleStartCreateTask()}
                />
              ) : null}
              {activeDrawer === 'map' ? (
              <PcdFileListPanel
                scenes={scenes}
                root={root}
                selectedSceneId={selectedSceneId}
                loading={loading}
                onRefresh={refreshScenes}
                onSelect={selectScene}
                onDeleteScene={requestDeleteScene}
              />
            ) : null}
          </div>
            {creatingTask ? (
              <div className="pcd-task-creator-drawer">
                <TaskCreatorDrawer
                  mode={taskEditorMode || 'create'}
                  draft={taskDraft}
                  maps={mapOptions}
                  selectedSceneId={selectedSceneId}
                  selectedSceneWaypoints={selectedSceneWaypoints}
                  selectedSceneNavigable={draftSceneNavigable}
                  selectedSceneMessage={draftSceneMessage}
                  canSaveTask={draftSceneNavigable}
                  onDraftChange={handleTaskDraftChange}
                  onAddDraftStep={handleAddDraftStep}
                  onRemoveDraftWaypoint={handleRemoveDraftWaypoint}
                  onDraftStepChange={handleDraftStepChange}
                  onCancelCreate={handleCancelCreateTask}
                  onCreateTask={handleCreateTask}
                />
              </div>
            ) : null}
          </div>

          <div className="pcd-overlay-stack">
            <section className={`pcd-panel pcd-floating-panel pcd-info-drawer ${infoOpen ? 'is-open' : 'is-closed'}`}>
                <button
                  className="pcd-info-toggle"
                onClick={() => setInfoOpen((value) => !value)}
                title={infoOpen ? '收起场景和位姿信息' : '展开场景和位姿信息'}
              >
                <div>
                  <strong>场景信息 / 机器狗坐标</strong>
                  <span>{metadata?.name || '未选择场景'}</span>
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
              disabled={!robotPose}
              title={!robotPose ? '等待机器狗定位数据' : undefined}
            >
              <LocateFixed size={15} />
              <span>{followRobot ? '解除跟随' : '视角跟随'}</span>
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
              disabled={!canOperate || !selectedSceneNavigable || !webglSupported}
              title={!webglSupported ? '当前浏览器无法使用 3D 点云标记' : !selectedSceneNavigable ? '当前场景缺少 ground.pcd' : undefined}
            >
              <Crosshair size={15} />
              <span>重定位</span>
            </button>
            <button
              className={`pcd-tool-button ${keyboardControlEnabled ? 'is-active' : ''}`}
              onClick={() => setKeyboardControlEnabled((v) => !v)}
              disabled={!canOperate}
              title={keyboardControlEnabled ? '关闭键盘控制' : '开启键盘控制，方向键调节速度，W/S/Q/E 控制移动'}
            >
              <Keyboard size={15} />
              <span>{keyboardControlEnabled ? '控制中' : '移动控制'}</span>
            </button>
            <button
              className={`pcd-tool-button ${mappingActive ? 'is-active' : ''}`}
              onClick={() => {
                if (mappingActive) {
                  void handleStopMapping()
                  return
                }
                handleOpenMappingDialog()
              }}
              disabled={mappingSending || !canOperate}
            >
              <Square size={15} />
              <span>
                {mappingSending
                  ? (mappingActive ? '正在保存地图...' : '开始建图中')
                  : (mappingActive ? '结束建图' : '开始建图')}
              </span>
            </button>
            <button
              className="pcd-tool-button"
              onClick={() => {
                if (!selectedTaskId) return
                void handleStopTask(selectedTaskId)
              }}
              disabled={!canOperate || !selectedTaskId}
              title={!selectedTaskId ? '先选择一个任务' : undefined}
            >
              <Square size={15} />
              <span>停止任务</span>
            </button>
            <button
              className="pcd-tool-button"
              onClick={() => void handleCheckRadar()}
              disabled={!canOperate || radarChecking}
              title="检查雷达 ROS2 topic、发布者和数据频率"
            >
              {radarChecking ? <Loader2 size={15} className="pcd-spin" /> : <Radar size={15} />}
              <span>{radarChecking ? '检查中' : '检查雷达'}</span>
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
                {!resultMessage && lastResult ? <small>{lastResult.result}</small> : null}
              </div>
            )}
          </section>
          {mappingSessionInfo ? (
            <section className="pcd-mapping-session">
              <strong>当前建图场景：{mappingSessionInfo.sceneName}</strong>
              <span>场景保存路径：{mappingSessionInfo.mapDir}</span>
            </section>
          ) : null}
        </section>

        <aside className="pcd-right-rail">
          <PointCloudTopDownCanvas
            layers={allLayers}
            viewKey={pointCloudViewKey}
            bounds={mappingActive ? liveMappingBounds : (preview?.bounds || metadata?.bounds || null)}
            waypoints={waypoints}
            robotPose={robotPose}
            globalPath={globalPath}
            mode="none"
            waypointZ={0}
            onMouseMapPositionChange={setMouseMapPosition}
            onAddWaypoint={handleAddWaypoint}
            onSetPose={handleSetPose}
          />
          <NavWaypointPanel
            waypoints={waypoints}
            navigatingWaypointId={navigatingWaypointId}
            sceneNavigable={selectedSceneNavigable}
            onGoTo={requestGoToWaypoint}
            onDelete={handleDeleteWaypoint}
          />
          <section className="pcd-rail-footer">
            <button
              className="pcd-estop-button"
              onClick={handleEmergencyStop}
              disabled={estopSending || !canOperate}
            >
              {estopSending ? '急停发送中' : '导航急停'}
            </button>
          </section>
        </aside>

        <section className={`pcd-message-center is-${currentNoticeKind} ${logsExpanded ? 'is-log-expanded' : ''}`} aria-live="polite">
          <div className="pcd-message-primary" title={currentNotice?.message || undefined}>
            <span className="pcd-message-label">提示中心</span>
            <strong>{currentNotice?.title || '待命'}</strong>
            <span>{currentNotice?.message || '无新的操作提醒。'}</span>
          </div>
          <div className="pcd-message-log">
            <button
              type="button"
              className="pcd-message-log-toggle"
              onClick={() => setLogsExpanded((value) => !value)}
              title={logsExpanded ? '收起导航日志' : '展开导航历史日志'}
              aria-expanded={logsExpanded}
            >
              <span className="pcd-message-label">最近日志</span>
              <span className={latestLog?.level === 'error' ? 'is-error' : ''}>
                {latestLog?.message || '等待操作日志'}
              </span>
              {logsExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {logsExpanded ? (
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
      </div>

      {/* ─── 导航到点二次确认弹窗 ─── */}
      {sceneDeleteConfirm !== null && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-white/10 bg-zinc-950 p-6 shadow-[0_30px_120px_-30px_rgba(0,0,0,0.9)]">
            <div className="text-lg font-black text-white">确认删除场景「{sceneDeleteConfirm.name}」</div>
            <div className="mt-3 space-y-1.5 text-sm text-zinc-400">
              <div>scene_id：{sceneDeleteConfirm.id}</div>
              <div>路径：{sceneDeleteConfirm.path}</div>
            </div>
            <p className="mt-4 text-xs text-amber-400/80">
              该操作会直接删除整个 SceneN_ 文件夹，且不可恢复。请确认该场景不再需要。
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                className="rounded-xl border border-white/12 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-white hover:border-white/30 hover:bg-white/5"
                onClick={() => setSceneDeleteConfirm(null)}
              >
                取消
              </button>
              <button
                className="rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-red-300 hover:border-red-400 hover:bg-red-500/20"
                onClick={() => {
                  void handleDeleteScene()
                }}
              >
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── 导航到点二次确认弹窗 ─── */}
      {goToConfirm !== null && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-white/10 bg-zinc-950 p-6 shadow-[0_30px_120px_-30px_rgba(0,0,0,0.9)]">
            <div className="text-lg font-black text-white">确认导航到「{goToConfirm.name}」</div>
            <div className="mt-3 space-y-1.5 text-sm text-zinc-400 font-mono">
              <div>map_id：{goToConfirm.map_id}</div>
              <div>x={goToConfirm.x.toFixed(3)} &nbsp; y={goToConfirm.y.toFixed(3)} &nbsp; z={goToConfirm.z.toFixed(3)}</div>
              <div>yaw={goToConfirm.yaw.toFixed(3)} rad</div>
            </div>
            <p className="mt-4 text-xs text-amber-400/80">发布导航请求后机器狗将开始移动到目标点。请确认周围安全。</p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                className="rounded-xl border border-white/12 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-white hover:border-white/30 hover:bg-white/5"
                onClick={() => setGoToConfirm(null)}
              >
                取消
              </button>
              <button
                className="rounded-xl border border-sky-500/40 bg-sky-500/10 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-sky-300 hover:border-sky-400 hover:bg-sky-500/20"
                onClick={() => {
                  const waypoint = goToConfirm
                  setGoToConfirm(null)
                  void handleGoToWaypoint(waypoint.id)
                }}
              >
                确认导航
              </button>
            </div>
          </div>
        </div>
      )}
      {mappingDialogOpen && typeof document !== 'undefined'
        ? createPortal(
            <div
              className="pcd-scene-modal"
              onClick={(event) => {
                if (event.target === event.currentTarget && !mappingSending) {
                  setMappingDialogOpen(false)
                  setMappingSceneError(null)
                }
              }}
            >
              <div className="pcd-scene-modal-card" role="dialog" aria-modal="true" aria-label="请输入场景名称">
                <div className="pcd-scene-modal-header">
                  <strong>请输入场景名称</strong>
                  <span>建图开始后会自动创建对应场景目录。</span>
                </div>
                <label className="pcd-scene-modal-field">
                  <span>场景名称</span>
                  <input
                    autoFocus
                    value={mappingSceneName}
                    onChange={(event) => {
                      setMappingSceneName(event.target.value)
                      if (mappingSceneError) {
                        setMappingSceneError(null)
                      }
                    }}
                    placeholder="例如：实验室一楼"
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault()
                        void handleConfirmStartMapping()
                      }
                    }}
                    disabled={mappingSending}
                  />
                </label>
                {mappingSceneError ? (
                  <div className="pcd-scene-modal-error">{mappingSceneError}</div>
                ) : null}
                <div className="pcd-scene-modal-actions">
                  <button
                    type="button"
                    className="pcd-tool-button"
                    onClick={() => {
                      setMappingDialogOpen(false)
                      setMappingSceneError(null)
                    }}
                    disabled={mappingSending}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="pcd-tool-button is-active"
                    onClick={() => void handleConfirmStartMapping()}
                    disabled={mappingSending}
                  >
                    {mappingSending ? '启动中...' : '确认开始'}
                  </button>
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
      {/* 建图时间过短时弹出确认 */}
      {mappingStopConfirmOpen && typeof document !== 'undefined'
        ? createPortal(
            <div
              className="pcd-scene-modal"
              onClick={(event) => {
                if (event.target === event.currentTarget) {
                  setMappingStopConfirmOpen(false)
                }
              }}
            >
              <div className="pcd-scene-modal-card" role="dialog" aria-modal="true" aria-label="确认停止建图">
                <div className="pcd-scene-modal-header">
                  <strong>确认停止建图</strong>
                  <span>
                    建图运行时间不足 {MIN_MAPPING_RUNTIME_SECONDS} 秒，
                    terrain_analysis 可能尚未启动或地面点云尚未保存。
                    建议继续等待至少 2 分钟后再停止。
                  </span>
                </div>
                <div className="pcd-scene-modal-actions">
                  <button
                    type="button"
                    className="pcd-tool-button"
                    onClick={() => setMappingStopConfirmOpen(false)}
                  >
                    继续等待
                  </button>
                  <button
                    type="button"
                    className="pcd-tool-button is-active"
                    onClick={() => {
                      setMappingStopConfirmOpen(false)
                      // 直接执行 stop，不再检查最小运行时间
                      setMappingSending(true)
                      setMappingEnabled(false).then((result) => {
                        setMappingActive(false)
                        setMappingSessionInfo(null)
                        setMappingStartTime(null)
                        setMappingSending(false)
                        if (result.saved) {
                          addLog(result.message || '地图已保存')
                          setTimeout(() => { void refreshScenes() }, 500)
                        } else {
                          const missing: string[] = []
                          if (result.map_pcd_candidates.length === 0) missing.push('map.pcd')
                          if (result.ground_pcd_candidates.length === 0) missing.push('ground.pcd')
                          addLog(
                            `地图保存不完整：缺少 ${missing.join('、')}，请查看 start_mapping_debug.log`,
                            'error',
                          )
                        }
                      }).catch((error) => {
                        addLog(error instanceof Error ? error.message : '停止建图失败', 'error')
                        setMappingSending(false)
                      })
                    }}
                    style={{ background: '#dc2626', borderColor: '#dc2626' }}
                  >
                    确认停止
                  </button>
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </main>
  )
}
