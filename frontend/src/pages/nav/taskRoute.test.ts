import { describe, expect, it } from 'vitest'
import { getDisplayedGlobalPath } from './navPageUtils'
import type { TaskRoute } from '../../types/navState'

const [start, first, middle, next, second, finish] = [-2, -1, 0, 1, 2, 3].map(x => ({ x, y: 0, z: 0 }))
const robotPoint = { x: 0.1, y: 0, z: 0 }
const robot = { ...robotPoint, yaw: 0, frame_id: 'map', source: 'tf', timestamp: 5 }
const route: TaskRoute = {
  task_id: 'task',
  run_id: 'run',
  frame_id: 'map',
  status: 'running',
  current_index: 1,
  segments: [
    { points: [start, first], waypoint: { ...first, name: 'A', yaw: 0 } },
    { points: [first, middle, next, second], waypoint: { ...second, name: 'B', yaw: 0 } },
    { points: [second, robotPoint, finish], waypoint: { ...finish, name: 'C', yaw: 0 } },
  ],
}

describe('task route display', () => {
  it('shows the entire route when planning is ready and execution has not started', () => {
    const ready: TaskRoute = { ...route, status: 'ready', current_index: 0 }
    expect(getDisplayedGlobalPath(null, robot, ready)?.points).toEqual(
      route.segments.flatMap(segment => segment.points),
    )
  })

  it('drops finished segments, trims the active one, and keeps later segments that pass near the robot', () => {
    expect(getDisplayedGlobalPath(null, robot, route)?.points).toEqual(
      [robotPoint, next, second, second, robotPoint, finish],
    )
    const laterRobot = { ...robot, x: next.x, timestamp: 6 }
    expect(getDisplayedGlobalPath(null, laterRobot, route)?.points).toEqual(
      [next, second, second, robotPoint, finish],
    )
  })

  it('uses the current segment during replanning and while the robot pose is unavailable', () => {
    const ready: TaskRoute = { ...route, status: 'ready' }
    const remaining = route.segments.slice(1).flatMap(segment => segment.points)
    expect(getDisplayedGlobalPath(null, robot, ready)?.points).toEqual(remaining)
    expect(getDisplayedGlobalPath(null, null, route)?.points).toEqual(remaining)
  })

  it('clears terminal task routes and still trims ordinary navigation', () => {
    const current = { frame_id: 'map', points: route.segments[1].points, timestamp: 4 }
    expect(getDisplayedGlobalPath(current, robot, { ...route, status: 'completed', current_index: 3 })).toBeNull()
    expect(getDisplayedGlobalPath(current, robot, { ...route, status: 'canceled', current_index: 0, segments: [] })).toBeNull()
    expect(getDisplayedGlobalPath(current, robot, null)?.points).toEqual([robotPoint, next, second])
  })
})
