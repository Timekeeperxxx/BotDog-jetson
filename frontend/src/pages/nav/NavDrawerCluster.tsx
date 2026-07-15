import { PcdFileListPanel } from '../../components/pcd/PcdFileListPanel'
import { TaskCreatorDrawer } from '../../components/pcd/TaskCreatorDrawer'
import { TaskDrawerPanel } from '../../components/pcd/TaskDrawerPanel'
import type { NavigationStatus } from '../../types/navState'
import type { PcdSceneItem } from '../../types/pcdMap'
import type { TaskDefinition, TaskDraft, TaskDraftStep } from '../../types/taskWorkflow'

type MapOption = {
  id: string
  name: string
}

type WaypointOption = {
  id: string
  name: string
}

type NavDrawerClusterProps = {
  activeDrawer: 'task' | 'map' | null
  canExecuteTask: boolean
  canSaveTask: boolean
  canStartCreate: boolean
  canStopTask: boolean
  creatingTask: boolean
  executingTaskId: string | null
  draft: TaskDraft
  maps: MapOption[]
  navigationStatus: NavigationStatus | null
  root: string
  scenes: PcdSceneItem[]
  scenesLoading: boolean
  selectedSceneId: string | null
  selectedSceneMessage: string | null
  selectedSceneNavigable: boolean
  selectedSceneWaypoints: WaypointOption[]
  selectedTaskId: string | null
  taskEditorMode: 'create' | 'edit' | null
  tasks: TaskDefinition[]
  onAddDraftStep: (index?: number) => void
  onCreateTask: () => void
  onDeleteScene: (scene: PcdSceneItem) => void
  onDeleteTask: (taskId: string) => void
  onDraftChange: (patch: Partial<TaskDraft>) => void
  onDraftStepChange: (index: number, patch: Partial<TaskDraftStep>) => void
  onEditTask: (taskId: string) => void
  onExecuteTask: (taskId: string) => void
  onRefreshScenes: () => void
  onRemoveDraftWaypoint: (index: number) => void
  onSelectScene: (sceneId: string) => void
  onSelectTask: (taskId: string) => void
  onSetActiveDrawer: (drawer: 'task' | 'map' | null) => void
  onStartCreate: () => void
  onStopTask: (taskId: string) => void
  onCancelCreate: () => void
}

export function NavDrawerCluster({
  activeDrawer,
  canExecuteTask,
  canSaveTask,
  canStartCreate,
  canStopTask,
  creatingTask,
  executingTaskId,
  draft,
  maps,
  navigationStatus,
  root,
  scenes,
  scenesLoading,
  selectedSceneId,
  selectedSceneMessage,
  selectedSceneNavigable,
  selectedSceneWaypoints,
  selectedTaskId,
  taskEditorMode,
  tasks,
  onAddDraftStep,
  onCreateTask,
  onDeleteScene,
  onDeleteTask,
  onDraftChange,
  onDraftStepChange,
  onEditTask,
  onExecuteTask,
  onRefreshScenes,
  onRemoveDraftWaypoint,
  onSelectScene,
  onSelectTask,
  onSetActiveDrawer,
  onStartCreate,
  onStopTask,
  onCancelCreate,
}: NavDrawerClusterProps) {
  return (
    <div className="pcd-drawer-cluster">
      <div className="pcd-drawer-rail">
        <button
          className={`pcd-drawer-toggle ${activeDrawer === 'task' ? 'is-active' : ''}`}
          onClick={() => onSetActiveDrawer(activeDrawer === 'task' ? null : 'task')}
          title={activeDrawer === 'task' ? '收起任务选择' : '展开任务选择'}
        >
          <span>任务选择</span>
        </button>
        <button
          className={`pcd-drawer-toggle ${activeDrawer === 'map' ? 'is-active' : ''}`}
          onClick={() => onSetActiveDrawer(activeDrawer === 'map' ? null : 'map')}
          title={activeDrawer === 'map' ? '收起场景选择' : '展开场景选择'}
        >
          <span>场景选择</span>
        </button>
      </div>
      <div className={`pcd-drawer-body pcd-shared-drawer-body ${activeDrawer ? 'is-open' : 'is-closed'}`}>
        {activeDrawer === 'task' ? (
          <TaskDrawerPanel
            tasks={tasks}
            selectedTaskId={selectedTaskId}
            navigationStatus={navigationStatus}
            canStartCreate={canStartCreate}
            canExecuteTask={canExecuteTask}
            canStopTask={canStopTask}
            executingTaskId={executingTaskId}
            onSelectTask={onSelectTask}
            onEditTask={onEditTask}
            onExecuteTask={onExecuteTask}
            onStopTask={onStopTask}
            onDeleteTask={onDeleteTask}
            onStartCreate={onStartCreate}
          />
        ) : null}
        {activeDrawer === 'map' ? (
          <PcdFileListPanel
            scenes={scenes}
            root={root}
            selectedSceneId={selectedSceneId}
            loading={scenesLoading}
            onRefresh={onRefreshScenes}
            onSelect={onSelectScene}
            onDeleteScene={onDeleteScene}
          />
        ) : null}
      </div>
      {creatingTask ? (
        <div className="pcd-task-creator-drawer">
          <TaskCreatorDrawer
            mode={taskEditorMode || 'create'}
            draft={draft}
            maps={maps}
            selectedSceneId={selectedSceneId}
            selectedSceneWaypoints={selectedSceneWaypoints}
            selectedSceneNavigable={selectedSceneNavigable}
            selectedSceneMessage={selectedSceneMessage}
            canSaveTask={canSaveTask}
            onDraftChange={onDraftChange}
            onAddDraftStep={onAddDraftStep}
            onRemoveDraftWaypoint={onRemoveDraftWaypoint}
            onDraftStepChange={onDraftStepChange}
            onCancelCreate={onCancelCreate}
            onCreateTask={onCreateTask}
          />
        </div>
      ) : null}
    </div>
  )
}
