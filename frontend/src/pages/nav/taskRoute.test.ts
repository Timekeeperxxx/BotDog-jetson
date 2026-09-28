import { describe, expect, it } from 'vitest'
import { getDisplayedGlobalPath } from './navPageUtils'
import type { TaskRoute } from '../../types/navState'

describe('task route display', () => {
  it('keeps the complete actual route after robot progress and completion; empty route clears it', () => {
    const points = [0, 1, 2, 3].map(x => ({ x, y: 0, z: 0 }))
    const route: TaskRoute = { task_id: 'task', run_id: 'run', frame_id: 'map', status: 'running', current_index: 1,
      segments: [{ points: points.slice(0, 2), waypoint: { ...points[1], name: 'A', yaw: 0 } },
        { points: points.slice(2), waypoint: { ...points[3], name: 'B', yaw: 0 } }] }
    const robot = { ...points[2], yaw: 0, frame_id: 'map', source: 'tf', timestamp: 5 }
    const current = { frame_id: 'map', points: points.slice(2), timestamp: 4 }
    expect(getDisplayedGlobalPath(current, robot, route)?.points).toEqual(points)
    expect(getDisplayedGlobalPath(current, robot, { ...route, status: 'completed' })?.points).toEqual(points)
    expect(getDisplayedGlobalPath(current, robot, { ...route, segments: [] })?.points).toEqual([])
    expect(getDisplayedGlobalPath(current, robot, null)?.points[0]).toEqual(points[2])
  })
})
