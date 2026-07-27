export type WorkflowNavigateWaypointStep = {
  type: 'navigate_waypoint'
  waypointId: string
  waypointName?: string
  x?: number
  y?: number
  z?: number
  yaw?: number
  frameId?: string
}

export type WorkflowPostureControlStep = {
  type: 'posture_control'
  posture: 'stand' | 'crouch'
}

export type WorkflowAutoTrackControlStep = {
  type: 'auto_track_control'
  enabled: boolean
}

export type WorkflowStep =
  | WorkflowNavigateWaypointStep
  | WorkflowPostureControlStep
  | WorkflowAutoTrackControlStep

export type TaskDefinition = {
  id: string
  name: string
  mapId: string
  sceneId?: string | null
  mapName: string
  createdAt: string
  autoTrackEnabled?: boolean | null
  steps: WorkflowStep[]
}

export type TaskDraftStep = WorkflowStep

export type TaskDraft = {
  name: string
  mapId: string
  steps: TaskDraftStep[]
}
