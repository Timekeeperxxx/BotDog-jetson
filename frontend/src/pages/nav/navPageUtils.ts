import type { LocalizationRestartResponse } from '../../api/pcdMapApi'
import type { GlobalPath, RobotPose } from '../../types/navState'
import type { PcdSceneItem } from '../../types/pcdMap'
export {
  DEFAULT_LINEAR_SPEED,
  DEFAULT_TURN_SPEED,
  MAX_LINEAR_SPEED,
  MAX_TURN_SPEED,
  SPEED_STEP,
  clampSpeed,
  formatSpeed,
  isArrowSpeedKey,
} from '../../utils/speedControl'
export { resolveRobotCommandFromKey } from '../../utils/keyboardRobotControl'
import type {
  TaskDefinition,
  TaskDraft,
  TaskDraftStep,
  WorkflowAutoTrackControlStep,
  WorkflowNavigateWaypointStep,
  WorkflowPostureControlStep,
  WorkflowStep,
} from '../../types/taskWorkflow'

type WaypointOption = {
  id: string
  name: string
}

export type LogItem = {
  id: number
  level: 'info' | 'error'
  timestamp: number
  message: string
}

export type MappingSessionInfo = {
  sceneName: string
  mapDir: string
}

export type RelocationPromptState =
  | { status: 'idle'; message: string }
  | { status: 'restarting' | 'waiting' | 'ready' | 'localized' | 'nav-waiting' | 'nav-ready' | 'error'; message: string }

export const emptyTaskDraft: TaskDraft = {
  name: '',
  mapId: '',
  steps: [],
}

export const WORKFLOW_STEP_TYPE_LABELS: Record<WorkflowStep['type'], string> = {
  navigate_waypoint: '导航到定点',
  posture_control: '姿态控制',
  auto_track_control: '自动跟踪联动',
}

export const POSTURE_LABELS: Record<'stand' | 'crouch', string> = {
  stand: '站立',
  crouch: '蹲下',
}

export const AUTO_TRACK_CONTROL_LABELS: Record<'enabled' | 'disabled', string> = {
  enabled: '开启自动跟踪',
  disabled: '关闭自动跟踪',
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

export function filterTasksByScene(tasks: TaskDefinition[], sceneId: string | null | undefined) {
  if (!sceneId) return []
  return tasks.filter((task) => resolveTaskSceneId(task) === sceneId)
}

export function createEmptyDraftStep(): TaskDraftStep {
  return createDraftStepByType('navigate_waypoint')
}

export function createDraftStepByType(type: WorkflowStep['type']): TaskDraftStep {
  if (type === 'posture_control') {
    return {
      type: 'posture_control',
      posture: 'stand',
    }
  }
  if (type === 'auto_track_control') {
    return {
      type: 'auto_track_control',
      enabled: true,
    }
  }
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

export function insertTaskDraftStep(current: TaskDraft, index: number | null | undefined): TaskDraft {
  const nextStep = createEmptyDraftStep()
  if (index == null || index < 0 || index >= current.steps.length - 1) {
    return {
      ...current,
      steps: [...current.steps, nextStep],
    }
  }

  const steps = current.steps.slice()
  steps.splice(index + 1, 0, nextStep)
  return {
    ...current,
    steps,
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
        ? patch.type && patch.type !== item.type
          ? createDraftStepByType(patch.type)
          : item.type === 'posture_control'
            ? {
                ...item,
                ...(patch as Partial<WorkflowPostureControlStep>),
                posture: (patch as Partial<WorkflowPostureControlStep>).posture ?? item.posture,
              }
            : item.type === 'auto_track_control'
              ? {
                  ...item,
                  ...(patch as Partial<WorkflowAutoTrackControlStep>),
                  enabled: (patch as Partial<WorkflowAutoTrackControlStep>).enabled ?? item.enabled,
                }
            : {
                ...item,
                ...(patch as Partial<WorkflowNavigateWaypointStep>),
                waypointId: (patch as Partial<WorkflowNavigateWaypointStep>).waypointId ?? item.waypointId,
              }
        : item
    )),
  }
}

export function compactRuntimeMessage(message: string) {
  if (message.includes('relocation 进程未运行')) {
    return 'Super-LIO 已退出，请重新重启导航定位。'
  }
  if (message.includes('/initialpose 暂无订阅者')) {
    return '还没有接收端，请稍后或重新重启导航定位。'
  }
  if (message.includes('target_frame does not exist') || message.includes('map') && message.includes('TF')) {
    return '未获取到 TF 位姿数据，请点击右上角“重启导航定位”开始标记位姿。'
  }
  if (message.includes('超时')) {
    return '等待超时，请查看日志后重试。'
  }
  return message.length > 56 ? `${message.slice(0, 56)}...` : message
}

export function getRelocationNotice(prompt: RelocationPromptState) {
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

export function summarizeLocalizationStatus(status: string, message: string) {
  if (status === 'ok') return message
  return compactRuntimeMessage(message)
}

export function trimGlobalPathByRobotPose(globalPath: GlobalPath | null, robotPose: RobotPose | null): GlobalPath | null {
  if (!globalPath || !robotPose) return globalPath
  if (globalPath.frame_id !== 'map' || robotPose.frame_id !== 'map') return globalPath
  if (globalPath.points.length < 2) return globalPath

  let nearestIndex = 0
  let nearestDistanceSq = Number.POSITIVE_INFINITY
  globalPath.points.forEach((point, index) => {
    const distanceSq = (point.x - robotPose.x) ** 2 + (point.y - robotPose.y) ** 2
    if (distanceSq < nearestDistanceSq) {
      nearestDistanceSq = distanceSq
      nearestIndex = index
    }
  })

  const nextIndex = Math.min(nearestIndex + 1, globalPath.points.length - 1)
  return {
    ...globalPath,
    timestamp: Math.max(globalPath.timestamp || 0, robotPose.timestamp || 0),
    points: [
      { x: robotPose.x, y: robotPose.y, z: robotPose.z },
      ...globalPath.points.slice(nextIndex),
    ],
  }
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

  const scanRuntime = health.runtime_mode === 'navigation_scan'
  const processChecks = scanRuntime
    ? [
        ['Navigation', health.navigation_ok],
        ['livox', health.livox_ok],
        ['relocation', health.relocation_ok],
        ['global_planner', health.global_planner_ok],
        ['SCAN planner', health.scan_planner_ok],
        ['SCAN controller', health.scan_controller_ok],
        ['dynamic avoidance', health.dynamic_avoidance_ok],
        ['nav status', health.nav_status_monitor_ok],
      ] as const
    : [
        ['livox', health.livox_ok],
        ['relocation', health.relocation_ok],
        ['global_planner', health.global_planner_ok],
        ['p2p_move_base', health.p2p_move_base_ok],
      ] as const
  const processOk = processChecks.every(([, ok]) => Boolean(ok))

  if (processOk) {
    okParts.push(
      scanRuntime
        ? '进程：定位 / 全局规划 / SCAN 避障控制 / 状态闭环正常'
        : '进程：livox / relocation / global_planner / p2p_move_base 正常',
    )
  } else {
    const processIssues = processChecks
      .filter(([, ok]) => !ok)
      .map(([name]) => name)
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

  if (result.startup_ready) {
    return `导航定位进程已启动，等待标记初始位姿${okParts.length > 0 ? `；${okParts.join('；')}` : ''}`
  }

  const nextReasons = reasons.length > 0 ? reasons : ['健康检查未通过']
  return `导航定位已重启，但导航不可用：${nextReasons.join('；')}`
}

export function buildTaskDraftFromTask(task: TaskDefinition): TaskDraft {
  const steps: TaskDraftStep[] = []

  for (const step of task.steps) {
    if (step.type === 'navigate_waypoint') {
      const waypointId = String(step.waypointId || '').trim()
      if (!waypointId) continue
      steps.push({
        type: 'navigate_waypoint',
        waypointId,
        waypointName: step.waypointName?.trim() || undefined,
        x: step.x,
        y: step.y,
        z: step.z,
        yaw: step.yaw,
        frameId: step.frameId,
      })
      continue
    }

    if (step.type === 'posture_control' && (step.posture === 'stand' || step.posture === 'crouch')) {
      steps.push({
        type: 'posture_control',
        posture: step.posture,
      })
      continue
    }

    if (step.type === 'auto_track_control' && typeof step.enabled === 'boolean') {
      steps.push({
        type: 'auto_track_control',
        enabled: step.enabled,
      })
    }
  }

  return {
    name: task.name,
    mapId: resolveTaskSceneId(task),
    steps,
  }
}

export function buildWorkflowStepsFromDraft(steps: TaskDraftStep[]): WorkflowStep[] {
  const workflowSteps: WorkflowStep[] = []

  for (const step of steps) {
    if (step.type === 'navigate_waypoint') {
      const waypointId = String(step.waypointId || '').trim()
      if (!waypointId) continue
      workflowSteps.push({
        type: 'navigate_waypoint',
        waypointId,
        waypointName: step.waypointName?.trim() || undefined,
        x: step.x,
        y: step.y,
        z: step.z,
        yaw: step.yaw,
        frameId: step.frameId,
      })
      continue
    }

    if (step.type === 'posture_control' && (step.posture === 'stand' || step.posture === 'crouch')) {
      workflowSteps.push({
        type: 'posture_control',
        posture: step.posture,
      })
      continue
    }

    if (step.type === 'auto_track_control' && typeof step.enabled === 'boolean') {
      workflowSteps.push({
        type: 'auto_track_control',
        enabled: step.enabled,
      })
    }
  }

  return workflowSteps
}

export function validateWorkflowStepsFromDraft(
  steps: TaskDraftStep[],
): { ok: false; message: string } | { ok: true; steps: WorkflowStep[] } {
  if (steps.length === 0) {
    return { ok: false, message: '任务流程至少需要一个步骤' }
  }

  const workflowSteps: WorkflowStep[] = []

  for (const [index, step] of steps.entries()) {
    const stepLabel = `第 ${index + 1} 步`

    if (step.type === 'navigate_waypoint') {
      const waypointId = String(step.waypointId || '').trim()
      if (!waypointId) {
        return { ok: false, message: `${stepLabel}导航到定点步骤必须选择导航点` }
      }
      workflowSteps.push({
        type: 'navigate_waypoint',
        waypointId,
        waypointName: step.waypointName?.trim() || undefined,
        x: step.x,
        y: step.y,
        z: step.z,
        yaw: step.yaw,
        frameId: step.frameId,
      })
      continue
    }

    if (step.type === 'posture_control') {
      if (step.posture !== 'stand' && step.posture !== 'crouch') {
        return { ok: false, message: `${stepLabel}姿态控制步骤必须选择姿态` }
      }
      workflowSteps.push({
        type: 'posture_control',
        posture: step.posture,
      })
      continue
    }

    if (step.type === 'auto_track_control') {
      if (typeof step.enabled !== 'boolean') {
        return { ok: false, message: `${stepLabel}自动跟踪联动步骤必须选择开启或关闭` }
      }
      workflowSteps.push({
        type: 'auto_track_control',
        enabled: step.enabled,
      })
      continue
    }

    return { ok: false, message: `${stepLabel}步骤类型无效` }
  }

  if (workflowSteps.length === 0) {
    return { ok: false, message: '任务流程至少需要一个有效步骤' }
  }

  return { ok: true, steps: workflowSteps }
}

export function buildTaskDefinitionFromDraft(params: {
  draft: TaskDraft
  scenes: PcdSceneItem[]
  tasks: TaskDefinition[]
  waypoints: WaypointOption[]
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

  const validatedWorkflowSteps = validateWorkflowStepsFromDraft(params.draft.steps)
  if (!validatedWorkflowSteps.ok) {
    return validatedWorkflowSteps
  }

  const waypointNameMap = new Map(params.waypoints.map((waypoint) => [waypoint.id, waypoint.name]))
  const workflowSteps = validatedWorkflowSteps.steps.map((step) => {
    if (step.type === 'navigate_waypoint') {
      return {
        ...step,
        waypointName: step.waypointName || waypointNameMap.get(step.waypointId) || undefined,
      }
    }
    return step
  })

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

export function getWorkflowStepTypeLabel(type: WorkflowStep['type']) {
  return WORKFLOW_STEP_TYPE_LABELS[type] || type
}

export function getWorkflowStepTargetLabel(step: TaskDraftStep | WorkflowStep, waypoints: WaypointOption[] = []) {
  if (step.type === 'posture_control') {
    return POSTURE_LABELS[step.posture]
  }
  if (step.type === 'auto_track_control') {
    return AUTO_TRACK_CONTROL_LABELS[step.enabled ? 'enabled' : 'disabled']
  }

  const waypointName = waypoints.find((waypoint) => waypoint.id === step.waypointId)?.name
  return waypointName || step.waypointName || step.waypointId || '未选择导航点'
}

export function summarizeWorkflowSteps(steps: Array<TaskDraftStep | WorkflowStep>, waypoints: WaypointOption[] = []) {
  return steps
    .map((step) => {
      if (step.type === 'navigate_waypoint') {
        const target = getWorkflowStepTargetLabel(step, waypoints)
        return `导航到${target}`
      }
      if (step.type === 'posture_control') {
        return POSTURE_LABELS[step.posture] || '姿态控制'
      }
      if (step.type === 'auto_track_control') {
        return AUTO_TRACK_CONTROL_LABELS[step.enabled ? 'enabled' : 'disabled']
      }
      return '无效步骤'
    })
    .join(' -> ')
}

export function taskContainsPostureControl(task: Pick<TaskDefinition, 'steps'>) {
  return task.steps.some((step) => step.type === 'posture_control')
}

export function countNavigateSteps(task: Pick<TaskDefinition, 'steps'>) {
  return task.steps.filter((step) => step.type === 'navigate_waypoint').length
}
