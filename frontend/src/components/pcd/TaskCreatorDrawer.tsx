import { ArrowLeft, Plus, Trash2, X } from 'lucide-react'
import type { TaskDraft, TaskDraftStep } from '../../types/taskWorkflow'

type MapOption = {
  id: string
  name: string
}

type WaypointOption = {
  id: string
  name: string
}

type Props = {
  mode: 'create' | 'edit'
  draft: TaskDraft
  maps: MapOption[]
  selectedSceneId: string | null
  selectedSceneWaypoints: WaypointOption[]
  selectedSceneNavigable: boolean
  selectedSceneMessage: string | null
  canSaveTask: boolean
  onDraftChange: (patch: Partial<TaskDraft>) => void
  onAddDraftWaypoint: () => void
  onRemoveDraftWaypoint: (index: number) => void
  onDraftWaypointChange: (index: number, patch: Partial<TaskDraftStep>) => void
  onCancelCreate: () => void
  onCreateTask: () => void
}

function stepValueLabel(step: TaskDraftStep) {
  return step.waypointId || '未选择导航点'
}

export function TaskCreatorDrawer({
  mode,
  draft,
  maps,
  selectedSceneId,
  selectedSceneWaypoints,
  selectedSceneNavigable,
  selectedSceneMessage,
  canSaveTask,
  onDraftChange,
  onAddDraftWaypoint,
  onRemoveDraftWaypoint,
  onDraftWaypointChange,
  onCancelCreate,
  onCreateTask,
}: Props) {
  return (
    <aside className="pcd-panel pcd-task-creator-panel">
      <div className="pcd-panel-header pcd-panel-header-compact">
        <div className="pcd-panel-header-main">
          <button className="pcd-editor-back" onClick={onCancelCreate}>
            <ArrowLeft size={14} />
            <span>返回任务列表</span>
          </button>
          <h2>{mode === 'create' ? '新建导航任务' : '编辑导航任务'}</h2>
        </div>
        <button className="pcd-icon-button" onClick={onCancelCreate} title="关闭编辑模式">
          <X size={16} />
        </button>
      </div>

      <div className="pcd-task-editor">
        <div className="pcd-task-editor-form">
          <label className="pcd-form-row">
            <span>任务名称</span>
            <input
              value={draft.name}
              onChange={(event) => onDraftChange({ name: event.target.value })}
              placeholder="请输入任务名称"
            />
          </label>

          <label className="pcd-form-row">
            <span>绑定场景</span>
            <select
              className="pcd-task-value-select"
              value={draft.mapId}
              onChange={(event) => onDraftChange({ mapId: event.target.value, steps: [] })}
            >
              <option value="">请选择场景</option>
              {maps.map((map) => (
                <option key={map.id} value={map.id}>
                  {map.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="pcd-task-flow-block">
          <div className="pcd-task-flow-head">
            <strong>导航流程</strong>
          </div>

          <div className="pcd-task-flow-list">
            {draft.steps.length === 0 ? (
              <button className="pcd-task-add-row" onClick={onAddDraftWaypoint}>
                <Plus size={16} />
                <span>添加导航点</span>
              </button>
            ) : null}

            {draft.steps.map((step, index) => (
              <div key={`draft-step-${index}`} className="pcd-flow-card">
                <div className="pcd-flow-card-main">
                  <div className="pcd-flow-card-index">{index + 1}</div>
                  <div className="pcd-flow-card-content">
                    <div className="pcd-flow-card-selects">
                      <select
                        className="pcd-task-value-select"
                        value={step.waypointId}
                        onChange={(event) => onDraftWaypointChange(index, { waypointId: event.target.value })}
                        disabled={!draft.mapId}
                      >
                        <option value="">{draft.mapId ? '请选择导航点' : '请先绑定场景'}</option>
                        {selectedSceneWaypoints.map((waypoint) => (
                          <option key={waypoint.id} value={waypoint.id}>
                            {waypoint.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="pcd-flow-card-meta">
                      <span>{`已选：${stepValueLabel(step)}`}</span>
                    </div>
                  </div>
                </div>
                <div className="pcd-flow-card-actions">
                  <button className="pcd-inline-icon-button" onClick={onAddDraftWaypoint} title="添加步骤">
                    <Plus size={14} />
                  </button>
                  <button
                    className="pcd-inline-icon-button"
                    onClick={() => onRemoveDraftWaypoint(index)}
                    disabled={draft.steps.length <= 1}
                    title="删除步骤"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>

          {draft.steps.length > 0 ? (
            <button className="pcd-task-add-row" onClick={onAddDraftWaypoint}>
              <Plus size={16} />
              <span>添加导航点</span>
            </button>
          ) : null}
        </div>

        <div className="pcd-task-editor-footer pcd-task-editor-footer-wide">
          <div className="pcd-task-editor-hint">
            任务必须绑定场景，任务名称不能为空。点击左侧任务卡片进入编辑，步骤通过下拉框配置。
            {draft.mapId && draft.mapId === selectedSceneId ? ' 当前场景已加载。' : ''}
            {!selectedSceneNavigable && selectedSceneMessage ? ` ${selectedSceneMessage}` : ''}
          </div>
          <div className="pcd-task-editor-actions pcd-task-editor-actions-wide">
            <button className="pcd-tool-button" onClick={onCancelCreate}>
              取消
            </button>
            <button className="pcd-primary-button pcd-save-button" onClick={onCreateTask} disabled={!canSaveTask}>
              {mode === 'create' ? '保存任务' : '保存修改'}
            </button>
          </div>
        </div>
      </div>
    </aside>
  )
}
