export type WorkflowStep =
  | { type: 'select_map'; label: string; mapId: string; sceneId?: string }
  | { type: 'relocalize'; label: string; mode: 'auto' | 'manual' | 'skip' }
  | {
      type: 'navigate_waypoint'
      label: string
      waypointId: string
      waypointName: string
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
  type: 'relocalize' | 'navigate_waypoint'
  relocalizeMode: 'auto' | 'manual' | 'skip'
  waypointId: string
}

export type TaskDraft = {
  name: string
  mapId: string
  steps: TaskDraftStep[]
}
