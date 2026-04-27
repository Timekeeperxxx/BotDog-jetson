import type { PcdMetadata } from '../../types/pcdMap'

type Props = {
  metadata: PcdMetadata | null
  mouseMapPosition: { x: number; y: number } | null
}

function fmt(value: number | undefined) {
  return typeof value === 'number' ? value.toFixed(3) : '-'
}

export function PcdMetadataPanel({ metadata, mouseMapPosition }: Props) {
  return (
    <section className="pcd-panel">
      <div className="pcd-panel-header">
        <div>
          <h2>地图信息</h2>
          <p>{metadata?.name || '未选择地图'}</p>
        </div>
      </div>

      {metadata ? (
        <div className="pcd-metadata-grid">
          <span>坐标系</span>
          <strong>{metadata.frame_id}</strong>
          <span>点数量</span>
          <strong>{metadata.point_count.toLocaleString()}</strong>
          <span>DATA</span>
          <strong>{metadata.data_type}</strong>
          <span>字段</span>
          <strong>{metadata.fields.join(', ')}</strong>
          <span>鼠标 X/Y</span>
          <strong>
            {mouseMapPosition
              ? `${mouseMapPosition.x.toFixed(3)}, ${mouseMapPosition.y.toFixed(3)}`
              : '-'}
          </strong>
        </div>
      ) : (
        <div className="pcd-empty">选择左侧 PCD 文件后显示 metadata</div>
      )}

      {metadata?.supported === false ? (
        <div className="pcd-warning">{metadata.message || '当前 PCD 类型暂不支持预览'}</div>
      ) : null}

      {metadata?.bounds ? (
        <div className="pcd-bounds">
          <div>X: {fmt(metadata.bounds.min_x)} / {fmt(metadata.bounds.max_x)}</div>
          <div>Y: {fmt(metadata.bounds.min_y)} / {fmt(metadata.bounds.max_y)}</div>
          <div>Z: {fmt(metadata.bounds.min_z)} / {fmt(metadata.bounds.max_z)}</div>
        </div>
      ) : null}
    </section>
  )
}
