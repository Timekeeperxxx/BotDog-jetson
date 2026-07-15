import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  deleteNavTask,
  executeNavTask,
  listNavTasks,
  saveNavTask,
  stopNavTask,
} from '../../api/pcdMapApi'
import type { GlobalPath, LocalizationStatus, NavigationStatus, RobotPose } from '../../types/navState'
import type { PcdSceneItem } from '../../types/pcdMap'
import type { TaskDefinition, TaskDraft, TaskDraftStep } from '../../types/taskWorkflow'
import {
  applyTaskDraftPatch,
  appendTaskDraftStep,
  buildTaskDefinitionFromDraft,
  buildTaskDraftFromTask,
  emptyTaskDraft,
  findSceneById,
  findTaskById,
  insertTaskDraftStep,
  patchTaskDraftStep,
  removeTaskDraftStep,
  resolveInitialTaskMapId,
} from './navPageUtils'
import type { LogItem } from './navPageUtils'

type InitialStatePayload = {
  robotPose?: RobotPose | null
  globalPath?: GlobalPath | null
  executionPath?: GlobalPath | null
  localizationStatus?: LocalizationStatus | null
  navigationStatus?: NavigationStatus | null
}

type WaypointOption = {
  id: string
  name: string
}

type UseNavTasksOptions = {
  addLog: (message: string, level?: LogItem['level']) => void
  canOperate: boolean
  openTaskDrawer: () => void
  scenes: PcdSceneItem[]
  selectScene: (sceneId: string) => Promise<boolean>
  selectedSceneId: string | null
  selectedSceneNavigable: boolean
  selectedSceneWaypoints: WaypointOption[]
  setInitialState: (state: InitialStatePayload) => void
  setNavigatingWaypointId: (waypointId: string | null) => void
}

export function useNavTasks({
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
}: UseNavTasksOptions) {
  const [tasks, setTasks] = useState<TaskDefinition[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [creatingTask, setCreatingTask] = useState(false)
  const [taskEditorMode, setTaskEditorMode] = useState<'create' | 'edit' | null>(null)
  const [taskDraft, setTaskDraft] = useState<TaskDraft>(emptyTaskDraft)
  const [executingTaskId, setExecutingTaskId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const loadTasks = async () => {
      try {
        const data = await listNavTasks()
        if (!cancelled) {
          setTasks(Array.isArray(data.items) ? data.items : [])
        }
      } catch (error) {
        if (!cancelled) {
          addLog(error instanceof Error ? error.message : '任务工作流读取失败', 'error')
        }
      }
    }

    void loadTasks()
    return () => {
      cancelled = true
    }
  }, [addLog])

  const resolvedSelectedTaskId = useMemo(() => {
    if (selectedTaskId && tasks.some((task) => task.id === selectedTaskId)) return selectedTaskId
    return tasks[0]?.id ?? null
  }, [selectedTaskId, tasks])

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
    openTaskDrawer()
  }, [addLog, openTaskDrawer, scenes, selectedSceneId, selectedSceneNavigable])

  const handleStartEditTask = useCallback((taskId: string) => {
    const task = findTaskById(tasks, taskId)
    if (!task) return
    const nextDraft: TaskDraft = buildTaskDraftFromTask(task)
    setSelectedTaskId(task.id)
    setTaskDraft(nextDraft)
    setCreatingTask(true)
    setTaskEditorMode('edit')
    openTaskDrawer()
    if (task.mapId !== selectedSceneId) {
      void selectScene(task.mapId)
    }
  }, [openTaskDrawer, selectedSceneId, selectScene, tasks])

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
      selectedTaskId: resolvedSelectedTaskId,
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
      taskEditorMode === 'edit' && resolvedSelectedTaskId
        ? tasks.map((item) => (item.id === resolvedSelectedTaskId ? nextTask : item))
        : [nextTask, ...tasks]
    setTasks(nextTasks)
    setSelectedTaskId(nextTask.id)
    setCreatingTask(false)
    setTaskEditorMode(null)
    setTaskDraft(emptyTaskDraft)
    openTaskDrawer()
    addLog(taskEditorMode === 'edit' ? `已更新任务 ${name}` : `已创建任务工作流 ${name}`)
  }, [addLog, openTaskDrawer, resolvedSelectedTaskId, scenes, selectedSceneWaypoints, taskDraft, taskEditorMode, tasks])

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
    if (!task) {
      addLog('任务不存在或已被删除，请刷新任务列表', 'error')
      return
    }
    if (executingTaskId) {
      addLog('已有任务正在启动，请稍候', 'error')
      return
    }
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
    setExecutingTaskId(task.id)
    addLog(`正在启动导航任务 ${task.name}…`)
    try {
      if (task.mapId !== selectedSceneId) {
        addLog(`正在切换到任务场景 ${task.mapName}…`)
        const selected = await selectScene(task.mapId)
        if (!selected) {
          throw new Error(`任务场景 ${task.mapName} 切换失败，任务未启动`)
        }
      }
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
      const autoTrackText = result.auto_track?.requested
        ? result.auto_track.enabled
          ? `AI跟踪=${result.auto_track.state || '已启动'}`
          : `AI跟踪=未启动(${result.auto_track.message || '服务未启用'})`
        : 'AI跟踪=未开启'
      addLog(
        `已执行导航任务 ${task.name}，已发布 ${result.topic}=true、${result.task_start.topic}=true，${autoTrackText}`,
      )
    } catch (error) {
      addLog(error instanceof Error ? error.message : '执行导航任务失败', 'error')
    } finally {
      setExecutingTaskId(null)
    }
  }, [addLog, canOperate, executingTaskId, scenes, selectedSceneId, selectScene, setInitialState, setNavigatingWaypointId, tasks])

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
        executionPath: null,
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
  }, [addLog, canOperate, setInitialState, setNavigatingWaypointId, tasks])

  const handleStopSelectedTask = useCallback(() => {
    if (!resolvedSelectedTaskId) return
    void handleStopTask(resolvedSelectedTaskId)
  }, [handleStopTask, resolvedSelectedTaskId])

  return {
    creatingTask,
    draftSceneMessage,
    draftSceneNavigable,
    executingTaskId,
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
    selectedTaskId: resolvedSelectedTaskId,
    setSelectedTaskId,
    taskDraft,
    taskEditorMode,
    tasks,
  }
}
