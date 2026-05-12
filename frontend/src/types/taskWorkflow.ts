export type WorkflowStep = {
  type: 'navigate_waypoint'
  waypointId: string
  waypointName?: string
  x?: number
  y?: number
  z?: number
  yaw?: number
  frameId?: string
}

export type TaskDefinition = {
  id: string
  name: string
  mapId: string
  sceneId?: string | null
  mapName: string
  createdAt: string
  steps: WorkflowStep[]
}

export type TaskDraftStep = {
  type: 'navigate_waypoint'
  waypointId: string
}

export type TaskDraft = {
  name: string
  mapId: string
  steps: TaskDraftStep[]
}
