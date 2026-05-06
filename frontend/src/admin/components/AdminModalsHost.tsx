import { type Dispatch, type ReactNode, type SetStateAction } from 'react'
import type { VideoSource } from '../../types/admin'
import type { NavWaypoint } from '../../types/pcdMap'
import { ConfirmDialog, ToolbarButton } from '../AdminUi'
import type { SourceFormState } from '../hooks/useAdminVideoConfigData'

interface AdminModalsHostProps {
  waypointToDelete: NavWaypoint | null
  selectedMapId: string | null
  onCancelDeleteWaypoint: () => void
  onConfirmDeleteWaypoint: () => void
  sourceToDelete: VideoSource | null
  onCancelDeleteSource: () => void
  onConfirmDeleteSource: () => void
  sourceFormOpen: boolean
  sourceForm: SourceFormState
  onSourceFormChange: Dispatch<SetStateAction<SourceFormState>>
  onCloseSourceForm: () => void
  onSubmitSourceForm: () => void
  sourceLoading: boolean
}

export function AdminModalsHost({
  waypointToDelete,
  selectedMapId,
  onCancelDeleteWaypoint,
  onConfirmDeleteWaypoint,
  sourceToDelete,
  onCancelDeleteSource,
  onConfirmDeleteSource,
  sourceFormOpen,
  sourceForm,
  onSourceFormChange,
  onCloseSourceForm,
  onSubmitSourceForm,
  sourceLoading,
}: AdminModalsHostProps) {
  return (
    <>
      <ConfirmDialog
        open={waypointToDelete !== null}
        title="确认删除导航点"
        description={waypointToDelete
          ? [
            `点位名称：${waypointToDelete.name}`,
            `waypoint_id：${waypointToDelete.id}`,
            `map_id：${waypointToDelete.map_id || selectedMapId || '--'}`,
            `位置：${waypointToDelete.x.toFixed(2)} / ${waypointToDelete.y.toFixed(2)} / ${waypointToDelete.z.toFixed(2)}`,
            `yaw：${waypointToDelete.yaw.toFixed(3)}`,
            '提示：该操作会修改地图对应的 JSON 存储，不可恢复。',
          ].join('\n')
          : ''}
        confirmText="确认删除"
        onCancel={onCancelDeleteWaypoint}
        onConfirm={onConfirmDeleteWaypoint}
        danger
      />

      <ConfirmDialog
        open={sourceToDelete !== null}
        title="确认删除视频源"
        description={sourceToDelete
          ? [
            `source_id：${sourceToDelete.source_id}`,
            `name：${sourceToDelete.name}`,
            `label：${sourceToDelete.label}`,
            `type：${sourceToDelete.source_type}`,
            `WHEP：${sourceToDelete.whep_url || '--'}`,
            `RTSP：${sourceToDelete.rtsp_url || '--'}`,
            '提示：删除后操作台相关视频源不可用，该操作不可恢复。',
          ].join('\n')
          : ''}
        confirmText="确认删除"
        onCancel={onCancelDeleteSource}
        onConfirm={onConfirmDeleteSource}
        danger
      />

      {sourceFormOpen ? (
        <SourceFormModal
          form={sourceForm}
          onChange={onSourceFormChange}
          onClose={onCloseSourceForm}
          onSubmit={onSubmitSourceForm}
          loading={sourceLoading}
        />
      ) : null}
    </>
  )
}

function SourceFormModal({
  form,
  onChange,
  onClose,
  onSubmit,
  loading,
}: {
  form: SourceFormState
  onChange: Dispatch<SetStateAction<SourceFormState>>
  onClose: () => void
  onSubmit: () => void
  loading: boolean
}) {
  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
      <div className="w-full max-w-3xl rounded-3xl border border-white/10 bg-zinc-950 p-6 shadow-[0_30px_120px_-30px_rgba(0,0,0,0.9)]">
        <div className="text-lg font-black text-white">{form.source_id ? '编辑视频源' : '新增视频源'}</div>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <Field label="名称">
            <input value={form.name} onChange={(event) => onChange((prev) => ({ ...prev, name: event.target.value }))} className="field-input" />
          </Field>
          <Field label="标签">
            <input value={form.label} onChange={(event) => onChange((prev) => ({ ...prev, label: event.target.value }))} className="field-input" />
          </Field>
          <Field label="source_type">
            <select value={form.source_type} onChange={(event) => onChange((prev) => ({ ...prev, source_type: event.target.value as SourceFormState['source_type'] }))} className="field-input">
              <option value="whep">whep</option>
              <option value="rtsp">rtsp</option>
              <option value="usb">usb</option>
            </select>
          </Field>
          <Field label="sort_order">
            <input value={String(form.sort_order)} onChange={(event) => onChange((prev) => ({ ...prev, sort_order: Number(event.target.value) || 0 }))} className="field-input" />
          </Field>
          <Field label="WHEP URL">
            <input value={form.whep_url} onChange={(event) => onChange((prev) => ({ ...prev, whep_url: event.target.value }))} className="field-input" />
          </Field>
          <Field label="RTSP URL">
            <input value={form.rtsp_url} onChange={(event) => onChange((prev) => ({ ...prev, rtsp_url: event.target.value }))} className="field-input" />
          </Field>
        </div>
        <div className="mt-5 flex flex-wrap gap-5">
          <CheckField label="启用" checked={form.enabled} onChange={(checked) => onChange((prev) => ({ ...prev, enabled: checked }))} />
          <CheckField label="主摄像头" checked={form.is_primary} onChange={(checked) => onChange((prev) => ({ ...prev, is_primary: checked }))} />
          <CheckField label="AI 源" checked={form.is_ai_source} onChange={(checked) => onChange((prev) => ({ ...prev, is_ai_source: checked }))} />
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <ToolbarButton onClick={onClose}>取消</ToolbarButton>
          <ToolbarButton onClick={onSubmit} disabled={loading || !form.name || !form.label}>
            {loading ? '保存中' : '保存'}
          </ToolbarButton>
        </div>
      </div>
    </div>
  )
}

function Field({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <label className="block">
      <div className="mb-2 text-[10px] font-black uppercase tracking-[0.18em] text-zinc-500">{label}</div>
      {children}
    </label>
  )
}

function CheckField({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="flex items-center gap-3 text-sm text-zinc-200">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="h-4 w-4 accent-white" />
      <span>{label}</span>
    </label>
  )
}
