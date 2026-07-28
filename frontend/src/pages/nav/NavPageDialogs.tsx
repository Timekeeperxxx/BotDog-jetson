import { createPortal } from 'react-dom'
import type { NavWaypoint, PcdSceneItem } from '../../types/pcdMap'
import { useModalFocus } from '../../hooks/useModalFocus'

type SceneDeleteConfirmDialogProps = {
  scene: PcdSceneItem | null
  onCancel: () => void
  onConfirm: () => void
}

export function SceneDeleteConfirmDialog({
  scene,
  onCancel,
  onConfirm,
}: SceneDeleteConfirmDialogProps) {
  const dialogRef = useModalFocus<HTMLDivElement>({
    open: scene !== null,
    onClose: onCancel,
  })
  if (scene === null) return null

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
      <div
        ref={dialogRef}
        className="w-full max-w-md rounded-2xl border border-white/10 bg-zinc-950 p-6 shadow-[0_30px_120px_-30px_rgba(0,0,0,0.9)]"
        role="alertdialog"
        aria-modal="true"
        aria-label={`确认删除场景 ${scene.name}`}
        tabIndex={-1}
      >
        <div className="text-lg font-black text-white">确认删除场景「{scene.name}」</div>
        <div className="mt-3 space-y-1.5 text-sm text-zinc-400">
          <div>scene_id：{scene.id}</div>
          <div>路径：{scene.path}</div>
        </div>
        <p className="mt-4 text-xs text-amber-400/80">
          该操作会直接删除整个 SceneN_ 文件夹，且不可恢复。请确认该场景不再需要。
        </p>
        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            className="rounded-xl border border-white/12 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-white hover:border-white/30 hover:bg-white/5"
            onClick={onCancel}
          >
            取消
          </button>
          <button
            type="button"
            className="rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-red-300 hover:border-red-400 hover:bg-red-500/20"
            onClick={onConfirm}
          >
            确认删除
          </button>
        </div>
      </div>
    </div>
  )
}

type GoToWaypointConfirmDialogProps = {
  waypoint: NavWaypoint | null
  sending: boolean
  onCancel: () => void
  onConfirm: (waypoint: NavWaypoint) => void
}

export function GoToWaypointConfirmDialog({
  waypoint,
  sending,
  onCancel,
  onConfirm,
}: GoToWaypointConfirmDialogProps) {
  const dialogRef = useModalFocus<HTMLDivElement>({
    open: waypoint !== null,
    onClose: onCancel,
    closeOnEscape: !sending,
  })
  if (waypoint === null) return null

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
      <div
        ref={dialogRef}
        className="w-full max-w-md rounded-2xl border border-white/10 bg-zinc-950 p-6 shadow-[0_30px_120px_-30px_rgba(0,0,0,0.9)]"
        role="dialog"
        aria-modal="true"
        aria-label={`确认导航到 ${waypoint.name}`}
        tabIndex={-1}
      >
        <div className="text-lg font-black text-white">确认导航到「{waypoint.name}」</div>
        <div className="mt-3 space-y-1.5 text-sm text-zinc-400 font-mono">
          <div>map_id：{waypoint.map_id}</div>
          <div>x={waypoint.x.toFixed(3)} &nbsp; y={waypoint.y.toFixed(3)} &nbsp; z={waypoint.z.toFixed(3)}</div>
          <div>yaw={waypoint.yaw.toFixed(3)} rad</div>
        </div>
        <p className="mt-4 text-xs text-amber-400/80">发布导航请求后机器狗将开始移动到目标点。请确认周围安全。</p>
        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            className="rounded-xl border border-white/12 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-white hover:border-white/30 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={sending}
            onClick={onCancel}
          >
            取消
          </button>
          <button
            type="button"
            className="rounded-xl border border-sky-500/40 bg-sky-500/10 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-sky-300 hover:border-sky-400 hover:bg-sky-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={sending}
            onClick={() => onConfirm(waypoint)}
          >
            {sending ? '正在提交…' : '确认导航'}
          </button>
        </div>
      </div>
    </div>
  )
}

type MappingStartDialogProps = {
  open: boolean
  sceneName: string
  error: string | null
  preflightChecking: boolean
  sending: boolean
  onSceneNameChange: (value: string) => void
  onClearError: () => void
  onCancel: () => void
  onConfirm: () => void
}

export function MappingStartDialog({
  open,
  sceneName,
  error,
  preflightChecking,
  sending,
  onSceneNameChange,
  onClearError,
  onCancel,
  onConfirm,
}: MappingStartDialogProps) {
  const dialogRef = useModalFocus<HTMLDivElement>({
    open,
    onClose: onCancel,
    closeOnEscape: !sending,
  })
  if (!open || typeof document === 'undefined') return null

  return createPortal(
    <div
      className="pcd-scene-modal"
      onClick={(event) => {
        if (event.target === event.currentTarget && !sending) {
          onCancel()
        }
      }}
    >
      <div
        ref={dialogRef}
        className="pcd-scene-modal-card"
        role="dialog"
        aria-modal="true"
        aria-label="请输入场景名称"
        tabIndex={-1}
      >
        <div className="pcd-scene-modal-header">
          <strong>请输入场景名称</strong>
          <span>建图开始后会自动创建对应场景目录。</span>
        </div>
        <div className="pcd-mapping-start-warning" role="note">
          <strong>启动建图前请保持设备静止</strong>
          <span>
            请将机器人放在平整地面，雷达保持正常安装姿态并完全静止。
            点击开始后继续静止至少 5 秒，待实时点云稳定显示后再移动；固定前倾安装无需调平。
          </span>
        </div>
        <label className="pcd-scene-modal-field">
          <span>场景名称</span>
          <input
            autoFocus
            value={sceneName}
            onChange={(event) => {
              onSceneNameChange(event.target.value)
              if (error) {
                onClearError()
              }
            }}
            placeholder="例如：实验室一楼"
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                onConfirm()
              }
            }}
            disabled={sending}
          />
        </label>
        {error ? (
          <div className="pcd-scene-modal-error" role="alert">{error}</div>
        ) : null}
        <div className="pcd-scene-modal-actions">
          <button
            type="button"
            className="pcd-tool-button"
            onClick={onCancel}
            disabled={sending}
          >
            取消
          </button>
          <button
            type="button"
            className="pcd-tool-button is-active"
            onClick={onConfirm}
            disabled={sending}
          >
            {preflightChecking
              ? '正在检查雷达连接...'
              : sending ? '启动中，请勿移动...' : '已保持静止，开始建图'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

type MappingStopConfirmDialogProps = {
  open: boolean
  minRuntimeSeconds: number
  onCancel: () => void
  onConfirm: () => void
}

export function MappingStopConfirmDialog({
  open,
  minRuntimeSeconds,
  onCancel,
  onConfirm,
}: MappingStopConfirmDialogProps) {
  const dialogRef = useModalFocus<HTMLDivElement>({
    open,
    onClose: onCancel,
  })
  if (!open || typeof document === 'undefined') return null

  return createPortal(
    <div
      className="pcd-scene-modal"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onCancel()
        }
      }}
    >
      <div
        ref={dialogRef}
        className="pcd-scene-modal-card"
        role="dialog"
        aria-modal="true"
        aria-label="确认停止建图"
        tabIndex={-1}
      >
        <div className="pcd-scene-modal-header">
          <strong>确认停止建图</strong>
          <span>
            建图运行时间不足 {minRuntimeSeconds} 秒，
            terrain_analysis 可能尚未启动或地面点云尚未保存。
            建议继续等待至少 2 分钟后再停止。
          </span>
        </div>
        <div className="pcd-scene-modal-actions">
          <button
            type="button"
            className="pcd-tool-button"
            onClick={onCancel}
          >
            继续等待
          </button>
          <button
            type="button"
            className="pcd-tool-button is-active"
            onClick={onConfirm}
            style={{ background: '#dc2626', borderColor: '#dc2626' }}
          >
            确认停止
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
