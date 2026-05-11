import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react'
import { deleteNavTask, executeNavTask, listNavTasks, saveNavTask, stopNavTask } from '../../api/pcdMapApi'
import type { GlobalPath, NavigationStatus } from '../../types/navState'
import type { NavWaypoint, PcdSceneItem } from '../../types/pcdMap'
import type { TaskDefinition, TaskDraft, TaskDraftStep, WorkflowStep } from '../../types/taskWorkflow'

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

type InitialStatePayload = {
  globalPath?: GlobalPath | null
  navigationStatus?: NavigationStatus | null
}

export type UseNavTasksOptions = {
  canOperate: boolean
  scenes: PcdSceneItem[]
  selectedSceneId: string | null
  selectedSceneNavigable: boolean
  waypoints: NavWaypoint[]
  setNavigatingWaypointId: Dispatch<SetStateAction<string | null>>
  setInitialState: (state: InitialStatePayload) => void
  selectScene: (sceneId: string) => Promise<void>
  onLog: (message: string, level?: 'info' | 'error') => void
}

export function useNavTasks({
  canOperate,
  scenes,
  selectedSceneId,
  selectedSceneNavigable,
  waypoints,
  setNavigatingWaypointId,
  setInitialState,
  selectScene,
  onLog,
}: UseNavTasksOptions) {
  const [tasks, setTasks] = useState<TaskDefinition[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [creatingTask, setCreatingTask] = useState(false)
  const [taskEditorMode, setTaskEditorMode] = useState<'create' | 'edit' | null>(null)
  const [taskDraft, setTaskDraft] = useState<TaskDraft>(emptyTaskDraft)
  const [activeDrawer, setActiveDrawer] = useState<'task' | 'map' | null>(null)

  const refreshTasks = useCallback(async () => {
    try {
      const data = await listNavTasks()
      setTasks(Array.isArray(data.items) ? data.items : [])
    } catch (error) {
      onLog(error instanceof Error ? error.message : '任务工作流读取失败', 'error')
    }
  }, [onLog])

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

  const draftScene = useMemo(
    () => scenes.find((scene) => scene.id === taskDraft.mapId) ?? null,
    [scenes, taskDraft.mapId],
  )
  const draftSceneNavigable = draftScene?.navigable ?? false
  const draftSceneMessage = draftScene?.message ?? null

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
      onLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
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
  }, [onLog, scenes, selectedSceneId, selectedSceneNavigable])

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
      onLog('任务名称不能为空', 'error')
      return
    }
    if (!taskDraft.mapId) {
      onLog('任务必须先绑定场景', 'error')
      return
    }

    const scene = scenes.find((item) => item.id === taskDraft.mapId)
    if (!scene) {
      onLog('任务关联场景不存在', 'error')
      return
    }

    if (!scene.navigable) {
      onLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
      return
    }

    if (taskDraft.steps.length === 0) {
      onLog('任务流程至少需要一个步骤', 'error')
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
      onLog('任务流程至少需要一个有效步骤', 'error')
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
      onLog(error instanceof Error ? error.message : '保存任务失败', 'error')
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
    onLog(taskEditorMode === 'edit' ? `已更新任务 ${name}` : `已创建任务工作流 ${name}`)
  }, [onLog, scenes, selectedSceneId, selectedTaskId, taskDraft, taskEditorMode, tasks, waypoints])

  const handleDeleteTask = useCallback(async (taskId: string) => {
    const task = tasks.find((item) => item.id === taskId)
    if (!task) return
    try {
      await deleteNavTask(task.id)
    } catch (error) {
      onLog(error instanceof Error ? error.message : '删除任务失败', 'error')
      return
    }
    const nextTasks = tasks.filter((item) => item.id !== task.id)
    setTasks(nextTasks)
    onLog(`已删除任务 ${task.name}`)
  }, [onLog, tasks])

  const handleExecuteTask = useCallback(async (taskId: string) => {
    if (!canOperate) {
      onLog('当前无操作权限，无法执行任务', 'error')
      return
    }

    const task = tasks.find((item) => item.id === taskId)
    if (!task) return
    setSelectedTaskId(task.id)
    const taskScene = scenes.find((item) => item.id === task.mapId)
    if (!taskScene) {
      onLog('任务关联场景不存在', 'error')
      return
    }
    if (!taskScene.navigable) {
      onLog('当前场景缺少 ground.pcd，不能用于导航', 'error')
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
      onLog(`已执行导航任务 ${task.name}，已发布 ${result.topic}=true`)
    } catch (error) {
      onLog(error instanceof Error ? error.message : '执行导航任务失败', 'error')
    }
  }, [canOperate, onLog, scenes, selectedSceneId, selectScene, setInitialState, setNavigatingWaypointId, tasks])

  const handleStopTask = useCallback(async (taskId: string) => {
    if (!canOperate) {
      onLog('当前无操作权限，无法停止任务', 'error')
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
      onLog(`已停止导航任务 ${task.name}，已发布 ${result.topic}=false`)
    } catch (error) {
      onLog(error instanceof Error ? error.message : '停止任务失败', 'error')
    }
  }, [canOperate, onLog, setInitialState, setNavigatingWaypointId, tasks])

  return {
    tasks,
    setTasks,
    selectedTaskId,
    setSelectedTaskId,
    creatingTask,
    setCreatingTask,
    taskEditorMode,
    setTaskEditorMode,
    taskDraft,
    setTaskDraft,
    activeDrawer,
    setActiveDrawer,
    selectedTask,
    selectedTaskScene,
    selectedTaskSceneNavigable,
    mapOptions,
    draftScene,
    draftSceneNavigable,
    draftSceneMessage,
    refreshTasks,
    handleTaskDraftChange,
    handleAddDraftWaypoint,
    handleRemoveDraftWaypoint,
    handleDraftWaypointChange,
    handleStartCreateTask,
    handleStartEditTask,
    handleCancelCreateTask,
    handleCreateTask,
    handleDeleteTask,
    handleExecuteTask,
    handleStopTask,
  }
}
