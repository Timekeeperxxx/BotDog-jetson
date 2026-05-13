import { describe, expect, it } from 'vitest'
import {
  applyTaskDraftPatch,
  appendTaskDraftStep,
  buildTaskDefinitionFromDraft,
  buildWorkflowStepsFromDraft,
  findSceneById,
  findTaskById,
  formatRestartHealthLog,
  getWorkflowStepTargetLabel,
  getWorkflowStepTypeLabel,
  insertTaskDraftStep,
  summarizeWorkflowSteps,
  taskContainsPostureControl,
  resolveInitialTaskMapId,
  resolveTaskSceneId,
  removeTaskDraftStep,
  patchTaskDraftStep,
  validateWorkflowStepsFromDraft,
  validateMappingSceneName,
} from './navPageUtils'

describe('navPageUtils', () => {
  it('validates mapping scene names', () => {
    expect(validateMappingSceneName('')).toEqual({ ok: false, message: '请输入场景名称' })
    expect(validateMappingSceneName('  实验室一楼  ')).toEqual({ ok: true, value: '实验室一楼' })
    expect(validateMappingSceneName('../bad')).toEqual({ ok: false, message: '场景名称不能包含 / 或 \\' })
  })

  it('formats restart health logs', () => {
    expect(
      formatRestartHealthLog({
        success: true,
        running: true,
        pid: 123,
        livox_pid: 1,
        relocation_pid: 2,
        global_planner_pid: 3,
        p2p_move_base_pid: 4,
        cmd_vel_pid: null,
        scene_id: 'Scene1_实验室一楼',
        navigation_ready: true,
        message: 'ok',
        health: null,
      }),
    ).toContain('导航定位已重启')
  })

  it('builds workflow steps from task draft steps', () => {
    expect(
      buildWorkflowStepsFromDraft([
        { type: 'navigate_waypoint', waypointId: '  wp-1  ' },
        { type: 'posture_control', posture: 'crouch' },
        { type: 'navigate_waypoint', waypointId: '' },
      ]),
    ).toEqual([
      { type: 'navigate_waypoint', waypointId: 'wp-1' },
      { type: 'posture_control', posture: 'crouch' },
    ])
  })

  it('validates workflow draft steps', () => {
    expect(
      validateWorkflowStepsFromDraft([
        { type: 'navigate_waypoint', waypointId: 'wp-1' },
        { type: 'posture_control', posture: 'stand' },
      ]),
    ).toEqual({
      ok: true,
      steps: [
        { type: 'navigate_waypoint', waypointId: 'wp-1', waypointName: undefined, x: undefined, y: undefined, z: undefined, yaw: undefined, frameId: undefined },
        { type: 'posture_control', posture: 'stand' },
      ],
    })

    expect(
      validateWorkflowStepsFromDraft([{ type: 'posture_control', posture: 'invalid' as never }]),
    ).toEqual({ ok: false, message: '第 1 步姿态控制步骤必须选择姿态' })
  })

  it('summarizes mixed workflow steps', () => {
    expect(
      summarizeWorkflowSteps(
        [
          { type: 'navigate_waypoint', waypointId: 'wp-1', waypointName: '巡检点1' },
          { type: 'posture_control', posture: 'stand' },
          { type: 'posture_control', posture: 'crouch' },
        ],
        [{ id: 'wp-1', name: '巡检点1' }],
      ),
    ).toBe('导航到巡检点1 -> 站立 -> 蹲下')
    expect(getWorkflowStepTypeLabel('navigate_waypoint')).toBe('导航到定点')
    expect(getWorkflowStepTargetLabel({ type: 'posture_control', posture: 'stand' })).toBe('站立')
    expect(taskContainsPostureControl({ steps: [{ type: 'posture_control', posture: 'stand' }] as any })).toBe(true)
  })

  it('builds task definitions with mixed workflow steps', () => {
    const result = buildTaskDefinitionFromDraft({
      draft: {
        name: '巡检任务',
        mapId: 'scene-a',
        steps: [
          { type: 'navigate_waypoint', waypointId: 'wp-1' },
          { type: 'posture_control', posture: 'stand' },
          { type: 'navigate_waypoint', waypointId: 'wp-2' },
        ],
      },
      scenes: [{ id: 'scene-a', name: '实验室一楼', navigable: true } as any],
      waypoints: [
        { id: 'wp-1', name: '巡检点1' },
        { id: 'wp-2', name: '巡检点2' },
      ],
      tasks: [],
      taskEditorMode: 'create',
      selectedTaskId: null,
    })

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.task.steps).toEqual([
        {
          type: 'navigate_waypoint',
          waypointId: 'wp-1',
          waypointName: '巡检点1',
          x: undefined,
          y: undefined,
          z: undefined,
          yaw: undefined,
          frameId: undefined,
        },
        { type: 'posture_control', posture: 'stand' },
        {
          type: 'navigate_waypoint',
          waypointId: 'wp-2',
          waypointName: '巡检点2',
          x: undefined,
          y: undefined,
          z: undefined,
          yaw: undefined,
          frameId: undefined,
        },
      ])
    }
  })

  it('resolves task scene identifiers', () => {
    expect(resolveTaskSceneId({ sceneId: 'scene-a', mapId: 'map-a' })).toBe('scene-a')
    expect(resolveTaskSceneId({ sceneId: null, mapId: 'map-a' })).toBe('map-a')
  })

  it('resolves initial task map id', () => {
    expect(resolveInitialTaskMapId('scene-a', ['map-a'])).toBe('scene-a')
    expect(resolveInitialTaskMapId(null, ['map-a', 'map-b'])).toBe('map-a')
    expect(resolveInitialTaskMapId(null, [])).toBe('')
  })

  it('finds tasks and scenes by id', () => {
    expect(findTaskById([{ id: 'task-a' } as never], 'task-a')).toEqual({ id: 'task-a' })
    expect(findTaskById([{ id: 'task-a' } as never], null)).toBeNull()
    expect(findSceneById([{ id: 'scene-a' } as never], 'scene-a')).toEqual({ id: 'scene-a' })
    expect(findSceneById([{ id: 'scene-a' } as never], undefined)).toBeNull()
  })

  it('updates task drafts immutably', () => {
    expect(
      applyTaskDraftPatch(
        { name: 'n', mapId: 'map-a', steps: [{ type: 'navigate_waypoint', waypointId: 'wp-1' }] },
        { mapId: 'map-b' },
      ),
    ).toEqual({ name: 'n', mapId: 'map-b', steps: [] })

    expect(
      appendTaskDraftStep({ name: 'n', mapId: 'map-a', steps: [] }).steps,
    ).toEqual([{ type: 'navigate_waypoint', waypointId: '' }])

    expect(
      insertTaskDraftStep(
        { name: 'n', mapId: 'map-a', steps: [{ type: 'navigate_waypoint', waypointId: 'wp-1' }] },
        0,
      ).steps,
    ).toEqual([
      { type: 'navigate_waypoint', waypointId: 'wp-1' },
      { type: 'navigate_waypoint', waypointId: '' },
    ])

    expect(
      removeTaskDraftStep(
        { name: 'n', mapId: 'map-a', steps: [{ type: 'navigate_waypoint', waypointId: 'wp-1' }] },
        0,
      ).steps,
    ).toEqual([])

    expect(
      patchTaskDraftStep(
        { name: 'n', mapId: 'map-a', steps: [{ type: 'navigate_waypoint', waypointId: 'wp-1' }] },
        0,
        { waypointId: 'wp-2' },
      ).steps,
    ).toEqual([{ type: 'navigate_waypoint', waypointId: 'wp-2' }])

    expect(
      patchTaskDraftStep(
        { name: 'n', mapId: 'map-a', steps: [{ type: 'navigate_waypoint', waypointId: 'wp-1' }] },
        0,
        { type: 'posture_control' },
      ).steps,
    ).toEqual([{ type: 'posture_control', posture: 'stand' }])
  })
})
