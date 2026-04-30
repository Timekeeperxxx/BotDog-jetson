import { Info, Play, Plus, Trash2 } from 'lucide-react'
import type { TaskDefinition } from '../../types/taskWorkflow'

type Props = {
  tasks: TaskDefinition[]
  selectedTaskId: string | null
  onSelectTask: (taskId: string) => void
  onEditTask: (taskId: string) => void
  onExecuteTask: () => void
  onDeleteTask: () => void
  onStartCreate: () => void
}

function waypointCount(task: TaskDefinition) {
  return task.steps.filter((step) => step.type === 'navigate_waypoint').length
}

function taskSummary(task: TaskDefinition) {
  return task.steps
    .filter((step) => step.type !== 'select_map')
    .map((step) => step.label)
    .join(' -> ')
}

export function TaskDrawerPanel({
  tasks,
  selectedTaskId,
  onSelectTask,
  onEditTask,
  onExecuteTask,
  onDeleteTask,
  onStartCreate,
}: Props) {
  const selectedTask = tasks.find((task) => task.id === selectedTaskId) ?? null

  return (
    <aside className="pcd-panel pcd-task-panel pcd-task-list-mode">
      <div className="pcd-panel-header pcd-panel-header-compact">
        <div className="pcd-panel-header-main">
          <h2>导航任务</h2>
          <p>{tasks.length === 0 ? '已保存 0 个任务' : `已保存 ${tasks.length} 个任务`}</p>
        </div>
      </div>

      <button className="pcd-task-create-hero" onClick={onStartCreate}>
        <Plus size={18} />
        <span>新建导航任务</span>
      </button>

      <div className="pcd-task-card-list">
        {tasks.length === 0 ? (
          <div className="pcd-empty">还没有导航任务，点击上方按钮开始创建。</div>
        ) : (
          tasks.map((task) => {
            const isActive = task.id === selectedTaskId
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
                  <span>地图：{task.mapName}</span>
                  <span>导航点：{waypointCount(task)} 个</span>
                  <span className="pcd-task-card-flow">流程：{taskSummary(task) || '未配置'}</span>
                  <span>状态：<strong className="pcd-task-status-pending">未执行</strong></span>
                </div>

                <div className="pcd-task-card-actions">
                  <button
                    className="pcd-tool-button"
                    onClick={(event) => {
                      event.stopPropagation()
                      onSelectTask(task.id)
                      onExecuteTask()
                    }}
                  >
                    <Play size={14} />
                    <span>执行</span>
                  </button>
                  <button
                    className="pcd-tool-button"
                    onClick={(event) => {
                      event.stopPropagation()
                      onSelectTask(task.id)
                      onDeleteTask()
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
          <span>绑定地图：{selectedTask.mapName}</span>
          <small>点击任务卡片右上角提示按钮进入编辑模式</small>
        </div>
      ) : null}
    </aside>
  )
}
