import { Info, Pause, Play, Plus, Trash2 } from 'lucide-react'
import type { NavigationStatus } from '../../types/navState'
import type { TaskDefinition } from '../../types/taskWorkflow'
import { summarizeWorkflowSteps } from '../../pages/nav/navPageUtils'

type Props = {
  tasks: TaskDefinition[]
  sceneName: string | null
  selectedTaskId: string | null
  navigationStatus: NavigationStatus | null
  canStartCreate: boolean
  canExecuteTask: boolean
  canStopTask: boolean
  executingTaskId: string | null
  taskLoopEnabled: Readonly<Record<string, boolean>>
  onSelectTask: (taskId: string) => void
  onEditTask: (taskId: string) => void
  onExecuteTask: (taskId: string, loop: boolean) => void
  onTaskLoopChange: (taskId: string, enabled: boolean) => void
  onStopTask: (taskId: string) => void
  onDeleteTask: (taskId: string) => void
  onStartCreate: () => void
}

export function TaskDrawerPanel({
  tasks,
  sceneName,
  selectedTaskId,
  navigationStatus,
  canStartCreate,
  canExecuteTask,
  canStopTask,
  executingTaskId,
  taskLoopEnabled,
  onSelectTask,
  onEditTask,
  onExecuteTask,
  onTaskLoopChange,
  onStopTask,
  onDeleteTask,
  onStartCreate,
}: Props) {
  const selectedTask = tasks.find((task) => task.id === selectedTaskId) ?? null
  const canStartTask = canExecuteTask && executingTaskId === null

  return (
    <aside className="pcd-panel pcd-task-panel pcd-task-list-mode">
      <div className="pcd-panel-header pcd-panel-header-compact">
        <div className="pcd-panel-header-main">
          <h2>导航任务</h2>
          <p>{sceneName ? `${sceneName} · ${tasks.length} 个任务` : '请先选择地图'}</p>
        </div>
      </div>

      <button className="pcd-task-create-hero" onClick={onStartCreate} disabled={!canStartCreate}>
        <Plus size={18} />
        <span>新建导航任务</span>
      </button>

      <div className="pcd-task-card-list">
        {tasks.length === 0 ? (
          <div className="pcd-empty">
            {sceneName ? '当前地图还没有导航任务，点击上方按钮开始创建。' : '选择地图后查看其导航任务。'}
          </div>
        ) : (
          tasks.map((task) => {
            const isActive = task.id === selectedTaskId
            const taskStatus = navigationStatus?.task_id === task.id ? navigationStatus.status : null
            const isPlanning = taskStatus === 'planning'
            const isRunning = taskStatus === 'navigating' || isPlanning
            const isStarting = executingTaskId === task.id
            const loopEnabled = taskLoopEnabled[task.id] === true
            const statusClassName = isRunning || isStarting ? 'pcd-task-status-running' : 'pcd-task-status-pending'
            const statusLabel = isStarting ? '启动中' : isPlanning ? '规划中' : isRunning ? '执行中' : '未执行'
            return (
              <article
                key={task.id}
                className={`pcd-task-card ${isActive ? 'is-active' : ''}`}
                onClick={() => onSelectTask(task.id)}
              >
                <div className="pcd-task-card-head">
                  <strong>{task.name}</strong>
                  <button
                    className="pcd-task-edit-chip"
                    onClick={(event) => {
                      event.stopPropagation()
                      onEditTask(task.id)
                    }}
                  >
                    <Info size={14} />
                    <span>点击任务卡片进入编辑</span>
                  </button>
                </div>

                <div className="pcd-task-card-grid">
                  <span>场景：{task.mapName}</span>
                  <span>步骤：{task.steps.length} 个</span>
                  <span className="pcd-task-card-flow">流程：{summarizeWorkflowSteps(task.steps) || '未配置'}</span>
                  <span>状态：<strong className={statusClassName}>{statusLabel}</strong></span>
                </div>

                <button
                  type="button"
                  className="pcd-task-loop-switch"
                  role="switch"
                  aria-label={task.name + ' 循环执行'}
                  aria-checked={loopEnabled}
                  disabled={!canStartTask}
                  title="下次点击执行时生效"
                  onClick={(event) => {
                    event.stopPropagation()
                    onTaskLoopChange(task.id, !loopEnabled)
                  }}
                >
                  <span className="pcd-task-loop-track" aria-hidden="true" />
                  <span>循环执行</span>
                </button>

                <div className="pcd-task-card-actions">
                  <button
                    className="pcd-tool-button"
                    onClick={(event) => {
                      event.stopPropagation()
                      onExecuteTask(task.id, loopEnabled)
                    }}
                    disabled={!canStartTask}
                    title={!canExecuteTask ? '当前账号没有任务执行权限' : isStarting ? '任务正在启动' : '执行此任务'}
                  >
                    <Play size={14} />
                    <span>{isStarting ? '启动中…' : '执行'}</span>
                  </button>
                  <button
                    className="pcd-tool-button"
                    onClick={(event) => {
                      event.stopPropagation()
                      onStopTask(task.id)
                    }}
                    disabled={!canStopTask}
                  >
                    <Pause size={14} />
                    <span>停止任务</span>
                  </button>
                  <button
                    className="pcd-tool-button"
                    onClick={(event) => {
                      event.stopPropagation()
                      onDeleteTask(task.id)
                    }}
                  >
                    <Trash2 size={14} />
                    <span>删除</span>
                  </button>
                </div>
              </article>
            )
          })
        )}
      </div>

      {selectedTask ? (
        <div className="pcd-task-summary">
          <strong>{selectedTask.name}</strong>
          <span>绑定场景：{selectedTask.mapName}</span>
          <small>点击任务卡片右上角提示按钮进入编辑模式</small>
        </div>
      ) : null}
    </aside>
  )
}
