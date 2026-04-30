import { RefreshCw } from 'lucide-react'
import type { PcdMapItem } from '../../types/pcdMap'

type Props = {
  maps: PcdMapItem[]
  selectedMapId: string | null
  root: string
  loading: boolean
  onRefresh: () => void
  onSelect: (mapId: string) => void
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
}

export function PcdFileListPanel({
  maps,
  selectedMapId,
  root,
  loading,
  onRefresh,
  onSelect,
}: Props) {
  return (
    <aside className="pcd-panel pcd-file-panel">
      <div className="pcd-panel-header pcd-panel-header-compact">
        <div className="pcd-panel-header-main">
          <h2>PCD 文件</h2>
          <p title={root}>{root || '尚未读取目录'}</p>
        </div>
        <button className="pcd-icon-button pcd-file-refresh" onClick={onRefresh} disabled={loading} title="刷新">
          <RefreshCw size={16} />
        </button>
      </div>

      <div className="pcd-file-list">
        {maps.length === 0 ? (
          <div className="pcd-empty">未发现 .pcd 文件</div>
        ) : (
          maps.map((map) => (
            <button
              key={map.id}
              className={`pcd-file-item ${selectedMapId === map.id ? 'is-active' : ''}`}
              onClick={() => onSelect(map.id)}
            >
              <span>{map.name}</span>
              <small>
                {formatBytes(map.size_bytes)} · {new Date(map.modified_at).toLocaleString()}
              </small>
            </button>
          ))
        )}
      </div>
    </aside>
  )
}
