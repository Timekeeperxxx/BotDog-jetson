export type WorkflowStep =
  | { type: 'select_map'; label: string; mapId: string }
  | { type: 'relocalize'; label: string; mode: 'auto' | 'manual' | 'skip' }
  | { type: 'navigate_waypoint'; label: string; waypointId: string; waypointName: string }

export type TaskDefinition = {
  id: string
  name: string
  mapId: string
  mapName: string
  createdAt: string
  steps: WorkflowStep[]
}

export type TaskDraftStep = {
  type: 'relocalize' | 'navigate_waypoint'
  relocalizeMode: 'auto' | 'manual' | 'skip'
  waypointId: string
}

export type TaskDraft = {
  name: string
  mapId: string
  steps: TaskDraftStep[]
}
