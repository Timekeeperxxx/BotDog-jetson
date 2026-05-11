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
  Square,
} from 'lucide-react'
import { getNavState } from '../api/navApi'
import {
  createWaypoint,
  deleteWaypoint,
  goToWaypoint,
  getPcdSceneMetadata,
  getPcdScenePreview,
  listPcdScenes,
  listNavTasks,
  listWaypoints,
  notifyNavPageOpen,
  deletePcdScene,
  deleteNavTask,
  executeNavTask,
  saveNavTask,
  stopNavTask,
  selectPcdScene,
  restartNavigationLocalization,
  setMappingEnabled,
  setLocalizationPose,
  triggerNavEmergencyStop,
} from '../api/pcdMapApi'
import { NavWaypointPanel } from '../components/pcd/NavWaypointPanel'
import { PcdFileListPanel } from '../components/pcd/PcdFileListPanel'
import { PointCloud3DViewer } from '../components/pcd/PointCloud3DViewer'
import { PointCloudTopDownCanvas } from '../components/pcd/PointCloudTopDownCanvas'
import { detectWebGLSupport } from '../components/pcd/webglSupport'
import { TaskCreatorDrawer } from '../components/pcd/TaskCreatorDrawer'
import { TaskDrawerPanel } from '../components/pcd/TaskDrawerPanel'
import { useRobotControl, type RobotCommand } from '../hooks/useRobotControl'
import { useNavWebSocket } from '../hooks/useNavWebSocket'
import { hasAuthSession, hasRole, useAuthState } from '../stores/authStore'
import type { NavWaypoint, PcdSceneItem, PcdSceneMetadata, PcdScenePreview } from '../types/pcdMap'
import type { TaskDefinition, TaskDraft, TaskDraftStep, WorkflowStep } from '../types/taskWorkflow'

type LogItem = {
  id: number
  level: 'info' | 'error'
  message: string
}

type MappingSessionInfo = {
  sceneName: string
  mapDir: string
}

function nowText() {
  return new Date().toLocaleTimeString()
}

function validateMappingSceneName(
  rawValue: string,
): { ok: false; message: string } | { ok: true; value: string } {
  const sceneName = rawValue.trim()
  if (!sceneName) {
    return { ok: false, message: '请输入场景名称' }
  }
  if (sceneName === '.' || sceneName === '..') {
    return { ok: false, message: '场景名称非法' }
  }
  if (sceneName.includes('/') || sceneName.includes('\\')) {
    return { ok: false, message: '场景名称不能包含 / 或 \\' }
  }
  if (sceneName.includes('..')) {
    return { ok: false, message: '场景名称不能包含 ..' }
  }
  if (Array.from(sceneName).some((char) => char.charCodeAt(0) < 32)) {
    return { ok: false, message: '场景名称包含非法控制字符' }
  }
  if (sceneName.length > 100) {
    return { ok: false, message: '场景名称过长' }
  }
  return { ok: true, value: sceneName }
}

const SELECTED_SCENE_STORAGE_KEY = 'botdog-nav-selected-scene'

const emptyTaskDraft: TaskDraft = {
  name: '',
  mapId: '',
  steps: [],
}

function createEmptyDraftStep(): TaskDraftStep {
  return {
    type: 'relocalize',
    relocalizeMode: 'auto',
    waypointId: '',
  }
}

export function PcdMapDemoPage() {
  useAuthState()
  const canOperate = hasAuthSession() && hasRole('operator')
  const previewPointLimit = 15000
  const [scenes, setScenes] = useState<PcdSceneItem[]>([])
  const [root, setRoot] = useState('')
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null
    return window.localStorage.getItem(SELECTED_SCENE_STORAGE_KEY)
  })
  const [metadata, setMetadata] = useState<PcdSceneMetadata | null>(null)
  const [preview, setPreview] = useState<PcdScenePreview | null>(null)
  const [waypoints, setWaypoints] = useState<NavWaypoint[]>([])
  const [loading, setLoading] = useState(false)
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
  const [waypointZ, setWaypointZ] = useState(-0.83)
  const [navigatingWaypointId, setNavigatingWaypointId] = useState<string | null>(null)
  const [estopSending, setEstopSending] = useState(false)
  const [restartLocalizationSending, setRestartLocalizationSending] = useState(false)
  const [mappingActive, setMappingActive] = useState(false)
  const [mappingSending, setMappingSending] = useState(false)
  const [mappingDialogOpen, setMappingDialogOpen] = useState(false)
  const [mappingSceneName, setMappingSceneName] = useState('')
  const [mappingSceneError, setMappingSceneError] = useState<string | null>(null)
  const [mappingSessionInfo, setMappingSessionInfo] = useState<MappingSessionInfo | null>(null)
  const [mouseMapPosition, setMouseMapPosition] = useState<{ x: number; y: number } | null>(null)
  const [logs, setLogs] = useState<LogItem[]>([])
  const [webglSupported, setWebglSupported] = useState(true)
  const [sceneDeleteConfirm, setSceneDeleteConfirm] = useState<PcdSceneItem | null>(null)
  // ── 高危操作确认 ──
  const [goToConfirm, setGoToConfirm] = useState<NavWaypoint | null>(null)
  const selectRequestRef = useRef(0)
  const navWs = useNavWebSocket()
  const { robotPose, globalPath, localizationStatus, setInitialState } = navWs
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

  const selectedScene = useMemo(
    () => scenes.find((scene) => scene.id === selectedSceneId) ?? null,
    [scenes, selectedSceneId],
  )

  const selectedSceneNavigable = selectedScene?.navigable ?? false
  const selectedSceneReady = selectedScene?.ready ?? false
  const selectedSceneMessage = selectedScene?.message ?? metadata?.message ?? null

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (selectedSceneId) {
      window.localStorage.setItem(SELECTED_SCENE_STORAGE_KEY, selectedSceneId)
    } else {
      window.localStorage.removeItem(SELECTED_SCENE_STORAGE_KEY)
    }
  }, [selectedSceneId])

  useEffect(() => {
    setWebglSupported(detectWebGLSupport())
  }, [])

  const refreshScenes = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listPcdScenes()
      setScenes(data.items)
      setRoot(data.root)
      addLog(`已刷新场景目录，共 ${data.items.length} 个场景文件夹`)
    } catch (error) {
      addLog(error instanceof Error ? error.message : '获取场景列表失败', 'error')
    } finally {
      setLoading(false)
    }
  }, [addLog])

  const selectScene = useCallback(async (sceneId: string) => {
    const requestId = ++selectRequestRef.current
    setLoading(true)

    try {
      const currentScene = await selectPcdScene(sceneId)
      if (requestId !== selectRequestRef.current) return

      setSelectedSceneId(currentScene.scene_id)
      setMetadata(null)
      setPreview(null)
      setWaypoints([])
      setAddMode(false)
      addLog(`当前选择导航场景：${currentScene.scene_id}`)
      addLog(`当前场景 map.pcd：${currentScene.map_pcd}`)
      addLog(`当前场景 ground.pcd：${currentScene.ground_pcd}`)

      const nextMetadata = await getPcdSceneMetadata(sceneId)
      if (requestId !== selectRequestRef.current) return
      setMetadata(nextMetadata)
      addLog(`已读取场景 metadata: ${sceneId}`)

      const [nextPreview, nextWaypoints] = await Promise.all([
        getPcdScenePreview(sceneId, previewPointLimit),
        listWaypoints(sceneId).catch(() => ({ items: [] as NavWaypoint[] })),
      ])
      if (requestId !== selectRequestRef.current) return
      setPreview(nextPreview)
      setWaypoints(nextWaypoints.items)
      const groundPoints = nextPreview.layers.ground?.points.length || 0
      const wallPoints = nextPreview.layers.wall?.points.length || 0
      addLog(`已加载场景预览点云：ground ${groundPoints.toLocaleString()} 点，wall ${wallPoints.toLocaleString()} 点`)

      try {
        const navState = await getNavState()
        if (requestId !== selectRequestRef.current) return
        setInitialState({
          robotPose: navState.robot_pose,
          globalPath: navState.global_path,
          localizationStatus: navState.localization_status,
          navigationStatus: navState.navigation_status,
        })
        addLog('已刷新导航实时状态')
      } catch (error) {
        if (requestId === selectRequestRef.current) {
          addLog(error instanceof Error ? error.message : '刷新导航状态失败', 'error')
        }
      }
    } catch (error) {
      if (requestId !== selectRequestRef.current) return
      addLog(error instanceof Error ? error.message : `加载场景失败: ${sceneId}`, 'error')
    } finally {
      if (requestId === selectRequestRef.current) {
        setLoading(false)
      }
    }
  }, [addLog, previewPointLimit, setInitialState])

  const handleAddWaypoint = useCallback(async (pos: { x: number; y: number; z: number; yaw: number }) => {
    if (!selectedSceneId) return
    if (!selectedSceneNavigable) {
      addLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
      return
    }

    const defaultName = `巡检点${waypoints.length + 1}`
    const name = window.prompt('导航点名称', defaultName)?.trim()
    if (!name) return

    try {
      await createWaypoint(selectedSceneId, {
        name,
        x: pos.x,
        y: pos.y,
        z: pos.z,
        yaw: pos.yaw,
        frame_id: 'map',
      })
      const nextWaypoints = await listWaypoints(selectedSceneId)
      setWaypoints(nextWaypoints.items)
      setAddMode(false)
      addLog(
        `已保存导航点 ${name}: x=${pos.x.toFixed(3)}, y=${pos.y.toFixed(3)}, z=${pos.z.toFixed(3)}, yaw=${pos.yaw.toFixed(3)}`,
      )
    } catch (error) {
      addLog(error instanceof Error ? error.message : '保存导航点失败', 'error')
    }
  }, [addLog, selectedSceneId, selectedSceneNavigable, waypoints.length])

  const handleSetPose = useCallback(async (pos: { x: number; y: number; yaw: number }) => {
    if (!selectedSceneId) return
    if (!canOperate || !selectedSceneNavigable) {
      addLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
      return
    }

    try {
      await setLocalizationPose({
        map_id: selectedSceneId,
        x: pos.x,
        y: pos.y,
        yaw: pos.yaw,
        frame_id: 'map',
      })
      setToolMode('none')
      addLog(
        `已保存重定位位姿并发送重定位信号: x=${pos.x.toFixed(3)}, y=${pos.y.toFixed(3)}, yaw=${pos.yaw.toFixed(3)}`,
      )
    } catch (error) {
      addLog(error instanceof Error ? error.message : '设置重定位位姿失败', 'error')
    }
  }, [addLog, canOperate, selectedSceneId, selectedSceneNavigable])

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

    setRestartLocalizationSending(true)
    try {
      const result = await restartNavigationLocalization()
      addLog(
        `导航定位已重启：${result.scene_id ?? '--'}，map=${result.map_pcd ?? '--'}，ground=${result.ground_pcd ?? '--'}，` +
          `livox=${result.livox_pid ?? 'null'}，relocation=${result.relocation_pid ?? 'null'}，` +
          `global_planner=${result.global_planner_pid ?? 'null'}，p2p_move_base=${result.p2p_move_base_pid ?? 'null'}，` +
          `cmd_vel=${result.cmd_vel_pid ?? 'null'}，ready=${result.navigation_ready ?? false}`,
      )
    } catch (error) {
      addLog(error instanceof Error ? error.message : '重启导航定位失败', 'error')
    } finally {
      setRestartLocalizationSending(false)
    }
  }, [addLog, canOperate, restartLocalizationSending])

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

  const handleStopMapping = useCallback(async () => {
    if (!canOperate) return
    if (mappingSending) return

    setMappingSending(true)
    try {
      const result = await setMappingEnabled(false)
      setMappingActive(false)
      setMappingSessionInfo(null)
      addLog(result.message || '已停止建图')
    } catch (error) {
      addLog(error instanceof Error ? error.message : '停止建图失败', 'error')
    } finally {
      setMappingSending(false)
    }
  }, [addLog, canOperate, mappingSending])

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

  useEffect(() => {
    void refreshScenes()
  }, [refreshScenes])

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
    if (selectedSceneId && scenes.some((item) => item.id === selectedSceneId)) {
      if (metadata?.scene_id !== selectedSceneId && !loading) {
        void selectScene(selectedSceneId)
      }
      return
    }

    if (scenes.length === 0) return

    const storedSceneId = typeof window === 'undefined'
      ? null
      : window.localStorage.getItem(SELECTED_SCENE_STORAGE_KEY)

    if (storedSceneId && scenes.some((item) => item.id === storedSceneId)) {
      void selectScene(storedSceneId)
      return
    }

    const readyScene = scenes.find((item) => item.ready)
    if (readyScene) {
      void selectScene(readyScene.id)
      return
    }

    if (selectedSceneId === null) {
      return
    }

    setSelectedSceneId(null)
    setMetadata(null)
    setPreview(null)
    setWaypoints([])
    addLog('当前没有可用于导航的场景')
  }, [addLog, loading, metadata?.scene_id, scenes, selectedSceneId, selectScene])

  useEffect(() => {
    if (!selectedTaskId && tasks.length > 0) {
      setSelectedTaskId(tasks[0].id)
    }
    if (selectedTaskId && !tasks.some((task) => task.id === selectedTaskId)) {
      setSelectedTaskId(tasks[0]?.id ?? null)
    }
  }, [selectedTaskId, tasks])

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
        setInitialState({
          robotPose: state.robot_pose,
          globalPath: state.global_path,
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
  }, [addLog, setInitialState])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((event.target as HTMLElement).tagName)) return
      if (event.repeat) return
      // 未登录或无 operator 权限：不响应控制快捷键
      if (!canOperate) return

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
      if (resolved !== 'none') {
        setAddMode(false)
      }
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

  const interactionMode: 'none' | 'waypoint' | 'pose' =
    addMode ? 'waypoint' : (toolMode === 'pose' ? 'pose' : 'none')

  const selectedTask = useMemo(
    () => tasks.find((task) => task.id === selectedTaskId) ?? null,
    [selectedTaskId, tasks],
  )

  const selectedTaskScene = useMemo(
    () => (selectedTask ? scenes.find((scene) => scene.id === (selectedTask.sceneId || selectedTask.mapId)) ?? null : null),
    [scenes, selectedTask],
  )
  const selectedTaskSceneNavigable = selectedTaskScene?.navigable ?? false

  const mapOptions = useMemo(
    () => scenes.map((scene) => ({ id: scene.id, name: scene.name })),
    [scenes],
  )

  const selectedSceneWaypoints = useMemo(
    () => waypoints.map((waypoint) => ({ id: waypoint.id, name: waypoint.name })),
    [waypoints],
  )

  const draftScene = useMemo(
    () => scenes.find((scene) => scene.id === taskDraft.mapId) ?? null,
    [scenes, taskDraft.mapId],
  )
  const draftSceneNavigable = draftScene?.navigable ?? false
  const draftSceneMessage = draftScene?.message ?? null

  const previewLayers = useMemo(
    () => [
      { role: 'ground' as const, points: preview?.layers.ground?.points ?? [] },
      { role: 'wall' as const, points: preview?.layers.wall?.points ?? [] },
    ],
    [preview],
  )

  const handleTaskDraftChange = useCallback((patch: Partial<TaskDraft>) => {
    setTaskDraft((current) => ({
      ...current,
      ...patch,
      steps: patch.mapId && patch.mapId !== current.mapId ? [] : (patch.steps ?? current.steps),
    }))
    if (patch.mapId && patch.mapId !== selectedSceneId) {
      void selectScene(patch.mapId)
    }
  }, [selectedSceneId, selectScene])

  const handleAddDraftWaypoint = useCallback(() => {
    setTaskDraft((current) => ({
      ...current,
      steps: [...current.steps, createEmptyDraftStep()],
    }))
  }, [])

  const handleRemoveDraftWaypoint = useCallback((index: number) => {
    setTaskDraft((current) => ({
      ...current,
      steps: current.steps.filter((_, itemIndex) => itemIndex !== index),
    }))
  }, [])

  const handleDraftWaypointChange = useCallback((index: number, patch: Partial<TaskDraftStep>) => {
    setTaskDraft((current) => ({
      ...current,
      steps: current.steps.map((item, itemIndex) => (
        itemIndex === index
          ? {
              ...item,
              ...patch,
              waypointId: patch.type === 'relocalize' ? '' : (patch.waypointId ?? item.waypointId),
              relocalizeMode: patch.type === 'navigate_waypoint' ? item.relocalizeMode : (patch.relocalizeMode ?? item.relocalizeMode),
            }
          : item
      )),
    }))
  }, [])

  const handleStartCreateTask = useCallback(async () => {
    if (!selectedSceneNavigable) {
      addLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
      return
    }

    if (!selectedSceneId && scenes[0]?.id) {
      setTaskDraft({
        ...emptyTaskDraft,
        mapId: scenes[0].id,
      })
    } else {
      setTaskDraft({
        ...emptyTaskDraft,
        mapId: selectedSceneId ?? '',
      })
    }
    setCreatingTask(true)
    setTaskEditorMode('create')
    setActiveDrawer('task')
  }, [addLog, scenes, selectedSceneId, selectedSceneNavigable])

  const handleStartEditTask = useCallback((taskId: string) => {
    const task = tasks.find((item) => item.id === taskId)
    if (!task) return
    const nextDraft: TaskDraft = {
      name: task.name,
      mapId: task.sceneId || task.mapId,
      steps: task.steps
        .filter((step) => step.type !== 'select_map')
        .map((step) => (
          step.type === 'relocalize'
            ? { type: 'relocalize', relocalizeMode: step.mode, waypointId: '' }
            : { type: 'navigate_waypoint', relocalizeMode: 'auto', waypointId: step.waypointId }
        )),
    }
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
    const name = taskDraft.name.trim()
    if (!name) {
      addLog('任务名称不能为空', 'error')
      return
    }
    if (!taskDraft.mapId) {
      addLog('任务必须先绑定场景', 'error')
      return
    }

    const scene = scenes.find((item) => item.id === taskDraft.mapId)
    if (!scene) {
      addLog('任务关联场景不存在', 'error')
      return
    }

    if (!scene.navigable) {
      addLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
      return
    }

    if (taskDraft.steps.length === 0) {
      addLog('任务流程至少需要一个步骤', 'error')
      return
    }

    const waypointSource = taskDraft.mapId === selectedSceneId ? waypoints : []
    const workflowSteps: WorkflowStep[] = []
    taskDraft.steps.forEach((step) => {
      if (step.type === 'relocalize') {
        workflowSteps.push({
          type: 'relocalize' as const,
          label:
            step.relocalizeMode === 'auto'
              ? '自动重定位'
              : step.relocalizeMode === 'manual'
                ? '手动确认重定位'
                : '跳过重定位',
          mode: step.relocalizeMode,
        })
        return
      }

      if (!step.waypointId.trim()) return
      const waypoint = waypointSource.find((item) => item.id === step.waypointId)
      if (!waypoint) return
      workflowSteps.push({
        type: 'navigate_waypoint' as const,
        label: `导航到 ${waypoint.name} (x=${waypoint.x.toFixed(2)}, y=${waypoint.y.toFixed(2)}, z=${waypoint.z.toFixed(2)}, yaw=${waypoint.yaw.toFixed(3)})`,
        waypointId: waypoint.id,
        waypointName: waypoint.name,
        x: waypoint.x,
        y: waypoint.y,
        z: waypoint.z,
        yaw: waypoint.yaw,
        frameId: waypoint.frame_id,
      })
    })

    if (workflowSteps.length === 0) {
      addLog('任务流程至少需要一个有效步骤', 'error')
      return
    }

    const nextTask: TaskDefinition = {
      id: taskEditorMode === 'edit' && selectedTaskId ? selectedTaskId : `task-${Date.now()}`,
      name,
      mapId: scene.id,
      sceneId: scene.id,
      mapName: scene.name,
      createdAt:
        taskEditorMode === 'edit'
          ? tasks.find((item) => item.id === selectedTaskId)?.createdAt || new Date().toISOString()
          : new Date().toISOString(),
      steps: [
        { type: 'select_map', label: `选择场景 ${scene.name}`, mapId: scene.id, sceneId: scene.id },
        ...workflowSteps,
      ],
    }

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
  }, [addLog, scenes, selectedSceneId, selectedTaskId, taskDraft, taskEditorMode, tasks, waypoints])

  const handleDeleteTask = useCallback(async (taskId: string) => {
    const task = tasks.find((item) => item.id === taskId)
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

    const task = tasks.find((item) => item.id === taskId)
    if (!task) return
    setSelectedTaskId(task.id)
    const taskScene = scenes.find((item) => item.id === task.mapId)
    if (!taskScene) {
      addLog('任务关联场景不存在', 'error')
      return
    }
    if (!taskScene.navigable) {
      addLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
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

    const task = tasks.find((item) => item.id === taskId)
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

  return (
    <main className="pcd-demo-page">
      <header className="pcd-demo-header">
        <div className="pcd-title-row">
          <div className="pcd-title-block">
            <h1>BotDog 导航巡逻</h1>
            <p>场景地图预览、标点、导航、位姿和日志统一压缩到单屏工作区</p>
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
            disabled={!canOperate || restartLocalizationSending}
            onClick={() => void handleRestartNavigationLocalization()}
          >
            {restartLocalizationSending ? '重启中...' : '重启导航定位'}
          </button>
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
            disabled={!preview || !selectedSceneNavigable}
            onClick={handleToggleWaypointMode}
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
                layers={previewLayers}
                waypoints={waypoints}
                robotPose={robotPose}
                globalPath={globalPath}
                followRobot={followRobot}
                centerHeight={waypointZ}
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
                  onAddDraftWaypoint={handleAddDraftWaypoint}
                  onRemoveDraftWaypoint={handleRemoveDraftWaypoint}
                  onDraftWaypointChange={handleDraftWaypointChange}
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
              disabled={!canOperate || !selectedSceneNavigable}
            >
              <Square size={15} />
              <span>设置位姿</span>
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
              <span>{mappingSending ? (mappingActive ? '结束建图中' : '开始建图中') : (mappingActive ? '结束建图' : '开始建图')}</span>
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
            <div className="pcd-keyboard-hint">
              <Keyboard size={15} />
              <span>{isControlling ? `键盘控制中: ${currentCmd}` : '键盘控制: WASD / QE / Shift / Ctrl'}</span>
              {resultMessage ? <small>{resultMessage}</small> : null}
              {!resultMessage && lastResult ? <small>{lastResult.result}</small> : null}
            </div>
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
            layers={previewLayers}
            bounds={preview?.bounds || metadata?.bounds || null}
            waypoints={waypoints}
            robotPose={robotPose}
            globalPath={globalPath}
            mode={interactionMode}
            waypointZ={waypointZ}
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
    </main>
  )
}
