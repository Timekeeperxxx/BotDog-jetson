import { ArrowLeft, MapPinned, Plus, Trash2, X } from 'lucide-react'
import type { TaskDraft, TaskDraftStep } from '../../types/taskWorkflow'
import {
  getWorkflowStepTargetLabel,
  getWorkflowStepTypeLabel,
  POSTURE_LABELS,
} from '../../pages/nav/navPageUtils'

type WaypointOption = {
  id: string
  name: string
}

type Props = {
  mode: 'create' | 'edit'
  draft: TaskDraft
  selectedSceneId: string | null
  selectedSceneName: string | null
  selectedSceneWaypoints: WaypointOption[]
  selectedSceneNavigable: boolean
  selectedSceneMessage: string | null
  canSaveTask: boolean
  onDraftChange: (patch: Partial<TaskDraft>) => void
  onAddDraftStep: (index?: number) => void
  onRemoveDraftWaypoint: (index: number) => void
  onDraftStepChange: (index: number, patch: Partial<TaskDraftStep>) => void
  onCancelCreate: () => void
  onCreateTask: () => void
}

export function TaskCreatorDrawer({
  mode,
  draft,
  selectedSceneId,
  selectedSceneName,
  selectedSceneWaypoints,
  selectedSceneNavigable,
  selectedSceneMessage,
  canSaveTask,
  onDraftChange,
  onAddDraftStep,
  onRemoveDraftWaypoint,
  onDraftStepChange,
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

          <div className="pcd-form-row">
            <span>绑定场景</span>
            <div className="pcd-task-scene-binding">
              <MapPinned size={17} />
              <div>
                <strong>{selectedSceneName || '未选择场景'}</strong>
                <small>{draft.mapId || '请先选择地图'}</small>
              </div>
              <em>随当前地图绑定</em>
            </div>
          </div>
        </div>

        <div className="pcd-task-flow-block">
          <div className="pcd-task-flow-head">
            <strong>导航流程</strong>
          </div>

          <div className="pcd-task-flow-list">
            {draft.steps.length === 0 ? (
              <button className="pcd-task-add-row" onClick={() => onAddDraftStep()}>
                <Plus size={16} />
                <span>添加步骤</span>
              </button>
            ) : null}

            {draft.steps.map((step, index) => (
              <div key={`draft-step-${index}`} className="pcd-flow-card">
                <div className="pcd-flow-card-main">
                  <div className="pcd-flow-card-index">{index + 1}</div>
                  <div className="pcd-flow-card-content">
                    <div className="pcd-flow-card-selects">
                      <select
                        className="pcd-task-type-select"
                        value={step.type}
                        onChange={(event) => onDraftStepChange(index, { type: event.target.value as TaskDraftStep['type'] })}
                        disabled={!draft.mapId}
                      >
                        <option value="navigate_waypoint">{getWorkflowStepTypeLabel('navigate_waypoint')}</option>
                        <option value="posture_control">{getWorkflowStepTypeLabel('posture_control')}</option>
                        <option value="auto_track_control">{getWorkflowStepTypeLabel('auto_track_control')}</option>
                      </select>
                      {step.type === 'navigate_waypoint' ? (
                        <select
                          className="pcd-task-value-select"
                          value={step.waypointId}
                          onChange={(event) => onDraftStepChange(index, { waypointId: event.target.value })}
                          disabled={!draft.mapId}
                        >
                          <option value="">{draft.mapId ? '请选择导航点' : '请先绑定场景'}</option>
                          {selectedSceneWaypoints.map((waypoint) => (
                            <option key={waypoint.id} value={waypoint.id}>
                              {waypoint.name}
                            </option>
                          ))}
                        </select>
                      ) : step.type === 'posture_control' ? (
                        <select
                          className="pcd-task-value-select"
                          value={step.posture}
                          onChange={(event) =>
                            onDraftStepChange(index, { posture: event.target.value as 'stand' | 'crouch' })
                          }
                          disabled={!draft.mapId}
                        >
                          <option value="stand">{POSTURE_LABELS.stand}</option>
                          <option value="crouch">{POSTURE_LABELS.crouch}</option>
                        </select>
                      ) : (
                        <select
                          className="pcd-task-value-select"
                          value={step.enabled ? 'enabled' : 'disabled'}
                          onChange={(event) =>
                            onDraftStepChange(index, { enabled: event.target.value === 'enabled' })
                          }
                          disabled={!draft.mapId}
                        >
                          <option value="enabled">开启自动跟踪</option>
                          <option value="disabled">关闭自动跟踪</option>
                        </select>
                      )}
                    </div>
                    <div className="pcd-flow-card-meta">
                      <span>{`已选：${getWorkflowStepTargetLabel(step, selectedSceneWaypoints)}`}</span>
                    </div>
                  </div>
                </div>
                <div className="pcd-flow-card-actions">
                  <button className="pcd-inline-icon-button" onClick={() => onAddDraftStep(index)} title="在此后插入步骤">
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
            <button className="pcd-task-add-row" onClick={() => onAddDraftStep()}>
              <Plus size={16} />
              <span>添加步骤</span>
            </button>
          ) : null}
        </div>

        <div className="pcd-task-editor-footer pcd-task-editor-footer-wide">
          <div className="pcd-task-editor-hint">
            任务与当前地图固定绑定，只能使用该地图中的导航点。任务名称不能为空，步骤通过下拉框配置。
            自动跟踪联动会在流程执行到该步骤时立即开启或关闭。
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
