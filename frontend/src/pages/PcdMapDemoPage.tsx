import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  setLocalizationPose,
  triggerNavEmergencyStop,
} from '../api/pcdMapApi'
import { NavWaypointPanel } from '../components/pcd/NavWaypointPanel'
import { PcdFileListPanel } from '../components/pcd/PcdFileListPanel'
import { PointCloud3DViewer } from '../components/pcd/PointCloud3DViewer'
import { PointCloudTopDownCanvas } from '../components/pcd/PointCloudTopDownCanvas'
import { TaskCreatorDrawer } from '../components/pcd/TaskCreatorDrawer'
import { TaskDrawerPanel } from '../components/pcd/TaskDrawerPanel'
import { useRobotControl, type RobotCommand } from '../hooks/useRobotControl'
import { useNavWebSocket } from '../hooks/useNavWebSocket'
import type { NavWaypoint, PcdMapItem, PcdMetadata, PcdPreview } from '../types/pcdMap'
import type { TaskDefinition, TaskDraft, TaskDraftStep, WorkflowStep } from '../types/taskWorkflow'

type LogItem = {
  id: number
  level: 'info' | 'error'
  message: string
}

function nowText() {
  return new Date().toLocaleTimeString()
}

const TASK_STORAGE_KEY = 'botdog-nav-workflows'

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
  const previewPointLimit = 15000
  const [maps, setMaps] = useState<PcdMapItem[]>([])
  const [root, setRoot] = useState('')
  const [selectedMapId, setSelectedMapId] = useState<string | null>(null)
  const [metadata, setMetadata] = useState<PcdMetadata | null>(null)
  const [preview, setPreview] = useState<PcdPreview | null>(null)
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

  const persistTasks = useCallback((nextTasks: TaskDefinition[]) => {
    setTasks(nextTasks)
    window.localStorage.setItem(TASK_STORAGE_KEY, JSON.stringify(nextTasks))
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

  const handleSetPose = useCallback(async (pos: { x: number; y: number; yaw: number }) => {
    if (!selectedMapId) return

    try {
      await setLocalizationPose({
        map_id: selectedMapId,
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
  }, [addLog, selectedMapId])

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
    try {
      const raw = window.localStorage.getItem(TASK_STORAGE_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw) as TaskDefinition[]
      setTasks(Array.isArray(parsed) ? parsed : [])
    } catch {
      addLog('任务工作流缓存读取失败', 'error')
    }
  }, [addLog])

  useEffect(() => {
    if (selectedMapId || maps.length === 0) return
    void selectMap(maps[0].id)
  }, [maps, selectedMapId, selectMap])

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

  const mapOptions = useMemo(
    () => maps.map((map) => ({ id: map.id, name: map.name })),
    [maps],
  )

  const selectedMapWaypoints = useMemo(
    () => waypoints.map((waypoint) => ({ id: waypoint.id, name: waypoint.name })),
    [waypoints],
  )

  const handleTaskDraftChange = useCallback((patch: Partial<TaskDraft>) => {
    setTaskDraft((current) => ({
      ...current,
      ...patch,
      steps: patch.mapId && patch.mapId !== current.mapId ? [] : (patch.steps ?? current.steps),
    }))
    if (patch.mapId && patch.mapId !== selectedMapId) {
      void selectMap(patch.mapId)
    }
  }, [selectedMapId, selectMap])

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
    if (!selectedMapId && maps[0]?.id) {
      setTaskDraft({
        ...emptyTaskDraft,
        mapId: maps[0].id,
      })
    } else {
      setTaskDraft({
        ...emptyTaskDraft,
        mapId: selectedMapId ?? '',
      })
    }
    setCreatingTask(true)
    setTaskEditorMode('create')
    setActiveDrawer('task')
  }, [maps, selectedMapId])

  const handleStartEditTask = useCallback((taskId: string) => {
    const task = tasks.find((item) => item.id === taskId)
    if (!task) return
    const nextDraft: TaskDraft = {
      name: task.name,
      mapId: task.mapId,
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
    if (task.mapId !== selectedMapId) {
      void selectMap(task.mapId)
    }
  }, [selectedMapId, selectMap, tasks])

  const handleCancelCreateTask = useCallback(() => {
    setCreatingTask(false)
    setTaskEditorMode(null)
    setTaskDraft(emptyTaskDraft)
  }, [])

  const handleCreateTask = useCallback(() => {
    const name = taskDraft.name.trim()
    if (!name) {
      addLog('任务名称不能为空', 'error')
      return
    }
    if (!taskDraft.mapId) {
      addLog('任务必须先绑定地图', 'error')
      return
    }

    const map = maps.find((item) => item.id === taskDraft.mapId)
    if (!map) {
      addLog('任务关联地图不存在', 'error')
      return
    }

    if (taskDraft.steps.length === 0) {
      addLog('任务流程至少需要一个步骤', 'error')
      return
    }

    const waypointSource = taskDraft.mapId === selectedMapId ? waypoints : []
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
        label: `导航到 ${waypoint.name}`,
        waypointId: waypoint.id,
        waypointName: waypoint.name,
      })
    })

    if (workflowSteps.length === 0) {
      addLog('任务流程至少需要一个有效步骤', 'error')
      return
    }

    const nextTask: TaskDefinition = {
      id: taskEditorMode === 'edit' && selectedTaskId ? selectedTaskId : `task-${Date.now()}`,
      name,
      mapId: map.id,
      mapName: map.name,
      createdAt:
        taskEditorMode === 'edit'
          ? tasks.find((item) => item.id === selectedTaskId)?.createdAt || new Date().toISOString()
          : new Date().toISOString(),
      steps: [
        { type: 'select_map', label: `选择地图 ${map.name}`, mapId: map.id },
        ...workflowSteps,
      ],
    }

    const nextTasks =
      taskEditorMode === 'edit' && selectedTaskId
        ? tasks.map((item) => (item.id === selectedTaskId ? nextTask : item))
        : [nextTask, ...tasks]
    persistTasks(nextTasks)
    setSelectedTaskId(nextTask.id)
    setCreatingTask(false)
    setTaskEditorMode(null)
    setTaskDraft(emptyTaskDraft)
    setActiveDrawer('task')
    addLog(taskEditorMode === 'edit' ? `已更新任务 ${name}` : `已创建任务工作流 ${name}`)
  }, [addLog, maps, persistTasks, selectedMapId, selectedTaskId, taskDraft, taskEditorMode, tasks, waypoints])

  const handleDeleteTask = useCallback(() => {
    if (!selectedTask) return
    const nextTasks = tasks.filter((task) => task.id !== selectedTask.id)
    persistTasks(nextTasks)
    addLog(`已删除任务 ${selectedTask.name}`)
  }, [addLog, persistTasks, selectedTask, tasks])

  const handleExecuteTask = useCallback(async () => {
    if (!selectedTask) return
    if (selectedTask.mapId !== selectedMapId) {
      await selectMap(selectedTask.mapId)
    }
    addLog(`开始执行任务 ${selectedTask.name}`)
    selectedTask.steps.forEach((step, index) => {
      addLog(`步骤 ${index + 1}: ${step.label}`)
    })
  }, [addLog, selectedMapId, selectedTask, selectMap])

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
            <PointCloud3DViewer
              points={preview?.points || []}
              waypoints={waypoints}
              robotPose={robotPose}
              followRobot={followRobot}
            />
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
                title={activeDrawer === 'map' ? '收起地图选择' : '展开地图选择'}
              >
                <span>地图选择</span>
              </button>
            </div>
            <div className={`pcd-drawer-body pcd-shared-drawer-body ${activeDrawer ? 'is-open' : 'is-closed'}`}>
              {activeDrawer === 'task' ? (
                <TaskDrawerPanel
                  tasks={tasks}
                  selectedTaskId={selectedTaskId}
                  onSelectTask={setSelectedTaskId}
                  onEditTask={handleStartEditTask}
                  onExecuteTask={() => void handleExecuteTask()}
                  onDeleteTask={handleDeleteTask}
                  onStartCreate={() => void handleStartCreateTask()}
                />
              ) : null}
              {activeDrawer === 'map' ? (
                <PcdFileListPanel
                  maps={maps}
                  root={root}
                  selectedMapId={selectedMapId}
                  loading={loading}
                  onRefresh={refreshMaps}
                  onSelect={selectMap}
                />
              ) : null}
            </div>
            {creatingTask ? (
              <div className="pcd-task-creator-drawer">
                <TaskCreatorDrawer
                  mode={taskEditorMode || 'create'}
                  draft={taskDraft}
                  maps={mapOptions}
                  selectedMapId={selectedMapId}
                  selectedMapWaypoints={selectedMapWaypoints}
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
            mode={interactionMode}
            waypointZ={waypointZ}
            onMouseMapPositionChange={setMouseMapPosition}
            onAddWaypoint={handleAddWaypoint}
            onSetPose={handleSetPose}
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
