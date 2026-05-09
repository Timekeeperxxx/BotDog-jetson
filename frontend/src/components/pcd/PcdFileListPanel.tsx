import { RefreshCw, Trash2 } from 'lucide-react'
import type { PcdSceneItem } from '../../types/pcdMap'
import { hasAuthSession, hasRole, useAuthState } from '../../stores/authStore'

type Props = {
  scenes: PcdSceneItem[]
  selectedSceneId: string | null
  root: string
  loading: boolean
  onRefresh: () => void
  onSelect: (sceneId: string) => void
  onDeleteScene: (scene: PcdSceneItem) => void
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
}

function fileStatusLabel(file: PcdSceneItem['wall'], fallback: string) {
  if (!file) return `缺少 ${fallback}`
  return `${file.name}`
}

export function SceneFolderListPanel({
  scenes,
  selectedSceneId,
  root,
  loading,
  onRefresh,
  onSelect,
  onDeleteScene,
}: Props) {
  useAuthState()
  const canDeleteScene = hasAuthSession() && hasRole('admin')

  return (
    <aside className="pcd-panel pcd-file-panel">
      <div className="pcd-panel-header pcd-panel-header-compact">
        <div className="pcd-panel-header-main">
          <h2>场景地图</h2>
          <p title={root}>{root || '尚未读取目录'}</p>
        </div>
        <button className="pcd-icon-button pcd-file-refresh" onClick={onRefresh} disabled={loading} title="刷新">
          <RefreshCw size={16} />
        </button>
      </div>

      <div className="pcd-file-list">
        {scenes.length === 0 ? (
          <div className="pcd-empty">未发现 SceneN_ 场景文件夹</div>
        ) : (
          scenes.map((scene) => (
            <button
              key={scene.id}
              className={`pcd-file-item ${selectedSceneId === scene.id ? 'is-active' : ''}`}
              onClick={() => onSelect(scene.id)}
            >
              <div className="pcd-file-item-main">
                <span>{scene.name}</span>
                <small>
                  {new Date(scene.modified_at).toLocaleString()} · {scene.ready ? '可完整显示' : '资源不完整'}
                </small>
                <small>
                  地面: {scene.ground ? fileStatusLabel(scene.ground, 'ground.pcd') : '缺少 ground.pcd'}
                </small>
                <small>
                  墙壁: {scene.wall ? fileStatusLabel(scene.wall, 'wall/map.pcd') : '缺少 wall/map.pcd'}
                </small>
                <small>{scene.ground ? `地面 ${formatBytes(scene.ground.size_bytes)}` : ''}</small>
                <small>{scene.wall ? `墙壁 ${formatBytes(scene.wall.size_bytes)}` : ''}</small>
                {scene.message ? <small className="text-amber-300">{scene.message}</small> : null}
              </div>
              <div className="pcd-file-item-actions">
                {canDeleteScene ? (
                  <button
                    className="pcd-icon-button danger pcd-scene-delete-button"
                    onClick={(event) => {
                      event.stopPropagation()
                      onDeleteScene(scene)
                    }}
                    title="删除场景文件夹"
                  >
                    <Trash2 size={15} />
                  </button>
                ) : null}
              </div>
            </button>
          ))
        )}
      </div>
    </aside>
  )
}

export const PcdFileListPanel = SceneFolderListPanel
