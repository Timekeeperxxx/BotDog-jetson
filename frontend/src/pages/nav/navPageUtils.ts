import type { LocalizationRestartResponse } from '../../api/pcdMapApi'
import type { RobotCommand } from '../../hooks/useRobotControl'
import type { PcdSceneItem } from '../../types/pcdMap'
import type { TaskDefinition, TaskDraft, TaskDraftStep, WorkflowStep } from '../../types/taskWorkflow'

export const emptyTaskDraft: TaskDraft = {
  name: '',
  mapId: '',
  steps: [],
}

export function resolveTaskSceneId(task: Pick<TaskDefinition, 'sceneId' | 'mapId'>) {
  return task.sceneId || task.mapId
}

export function resolveInitialTaskMapId(
  selectedSceneId: string | null,
  sceneIds: string[],
) {
  return selectedSceneId ?? sceneIds[0] ?? ''
}

export function findSceneById(scenes: PcdSceneItem[], sceneId: string | null | undefined) {
  if (!sceneId) return null
  return scenes.find((scene) => scene.id === sceneId) ?? null
}

export function findTaskById(tasks: TaskDefinition[], taskId: string | null | undefined) {
  if (!taskId) return null
  return tasks.find((task) => task.id === taskId) ?? null
}

export function createEmptyDraftStep(): TaskDraftStep {
  return {
    type: 'navigate_waypoint',
    waypointId: '',
  }
}

export function applyTaskDraftPatch(current: TaskDraft, patch: Partial<TaskDraft>): TaskDraft {
  return {
    ...current,
    ...patch,
    steps: patch.mapId && patch.mapId !== current.mapId ? [] : (patch.steps ?? current.steps),
  }
}

export function appendTaskDraftStep(current: TaskDraft): TaskDraft {
  return {
    ...current,
    steps: [...current.steps, createEmptyDraftStep()],
  }
}

export function removeTaskDraftStep(current: TaskDraft, index: number): TaskDraft {
  return {
    ...current,
    steps: current.steps.filter((_, itemIndex) => itemIndex !== index),
  }
}

export function patchTaskDraftStep(
  current: TaskDraft,
  index: number,
  patch: Partial<TaskDraftStep>,
): TaskDraft {
  return {
    ...current,
    steps: current.steps.map((item, itemIndex) => (
      itemIndex === index
        ? {
            ...item,
            ...patch,
            waypointId: patch.waypointId ?? item.waypointId,
          }
        : item
    )),
  }
}

export function nowText() {
  return new Date().toLocaleTimeString()
}

export function validateMappingSceneName(
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

export function formatRestartHealthLog(result: LocalizationRestartResponse) {
  const health = result.health
  if (!health) {
    return `导航定位已重启：${result.scene_id ?? '--'}，ready=${result.navigation_ready ?? false}`
  }

  const okParts: string[] = []
  const badParts: string[] = []

  if (health.scene_ok && health.scene_id) {
    okParts.push(`场景：${health.scene_id}`)
  } else if (!health.scene_ok) {
    badParts.push('场景目录不存在')
  }

  if (health.map_pcd_ok) {
    okParts.push('map.pcd：正常')
  } else {
    badParts.push('map.pcd 缺失')
  }

  if (health.ground_pcd_ok) {
    okParts.push('ground.pcd：正常')
  } else {
    badParts.push('ground.pcd 缺失')
  }

  if (health.tf_ok === true) {
    okParts.push('TF：正常')
  } else if (health.tf_ok === false) {
    badParts.push('TF 未就绪')
  } else {
    okParts.push('TF：未确认')
  }

  const processOk = [
    health.livox_ok,
    health.relocation_ok,
    health.global_planner_ok,
    health.p2p_move_base_ok,
  ].every(Boolean)

  if (processOk) {
    okParts.push('进程：livox / relocation / global_planner / p2p_move_base 正常')
  } else {
    const processIssues = [
      health.livox_ok ? null : 'livox',
      health.relocation_ok ? null : 'relocation',
      health.global_planner_ok ? null : 'global_planner',
      health.p2p_move_base_ok ? null : 'p2p_move_base',
    ].filter(Boolean)
    if (processIssues.length > 0) {
      badParts.push(`进程异常：${processIssues.join(' / ')}`)
    }
  }

  if (health.cmd_vel_test_publisher_running) {
    badParts.push('检测到 cmd_vel 测试发布器残留')
  }

  if (health.warnings.length > 0) {
    badParts.push(...health.warnings)
  }
  if (health.errors.length > 0) {
    badParts.push(...health.errors)
  }

  const reasons = Array.from(new Set(badParts.filter(Boolean)))

  if (result.navigation_ready) {
    return `导航定位已重启：导航可用${okParts.length > 0 ? `；${okParts.join('；')}` : ''}`
  }

  const nextReasons = reasons.length > 0 ? reasons : ['健康检查未通过']
  return `导航定位已重启，但导航不可用：${nextReasons.join('；')}`
}

export function resolveRobotCommandFromKey(key: string): RobotCommand | null {
  switch (key.toLowerCase()) {
    case 'w':
    case 'arrowup':
      return 'forward'
    case 's':
    case 'arrowdown':
      return 'backward'
    case 'a':
      return 'strafe_left'
    case 'd':
      return 'strafe_right'
    case 'q':
    case 'arrowleft':
      return 'left'
    case 'e':
    case 'arrowright':
      return 'right'
    case 'control':
      return 'sit'
    case 'shift':
      return 'stand'
    default:
      return null
  }
}

export function buildTaskDraftFromTask(task: TaskDefinition): TaskDraft {
  return {
    name: task.name,
    mapId: resolveTaskSceneId(task),
    steps: task.steps
      .filter((step) => step.type === 'navigate_waypoint' && Boolean(step.waypointId))
      .map((step) => ({ type: 'navigate_waypoint', waypointId: step.waypointId })),
  }
}

export function buildWorkflowStepsFromDraft(steps: TaskDraftStep[]): WorkflowStep[] {
  return steps
    .map((step) => {
      const waypointId = step.waypointId.trim()
      if (!waypointId) return null
      return {
        type: 'navigate_waypoint' as const,
        waypointId,
      }
    })
    .filter((step): step is WorkflowStep => step !== null)
}

export function buildTaskDefinitionFromDraft(params: {
  draft: TaskDraft
  scenes: PcdSceneItem[]
  tasks: TaskDefinition[]
  taskEditorMode: 'create' | 'edit' | null
  selectedTaskId: string | null
}): { ok: false; message: string } | { ok: true; task: TaskDefinition } {
  const name = params.draft.name.trim()
  if (!name) {
    return { ok: false, message: '任务名称不能为空' }
  }
  if (!params.draft.mapId) {
    return { ok: false, message: '任务必须先绑定场景' }
  }

  const scene = findSceneById(params.scenes, params.draft.mapId)
  if (!scene) {
    return { ok: false, message: '任务关联场景不存在' }
  }
  if (!scene.navigable) {
    return { ok: false, message: '当前场景缺少 ground.pcd，不能用于导航' }
  }
  if (params.draft.steps.length === 0) {
    return { ok: false, message: '任务流程至少需要一个步骤' }
  }

  const workflowSteps = buildWorkflowStepsFromDraft(params.draft.steps)
  if (workflowSteps.length === 0) {
    return { ok: false, message: '任务流程至少需要一个有效步骤' }
  }

  const nextTaskId =
    params.taskEditorMode === 'edit' && params.selectedTaskId ? params.selectedTaskId : `task-${Date.now()}`
  const createdAt =
    params.taskEditorMode === 'edit'
      ? findTaskById(params.tasks, params.selectedTaskId)?.createdAt || new Date().toISOString()
      : new Date().toISOString()

  return {
    ok: true,
    task: {
      id: nextTaskId,
      name,
      mapId: scene.id,
      sceneId: scene.id,
      mapName: scene.name,
      createdAt,
      steps: workflowSteps,
    },
  }
}
