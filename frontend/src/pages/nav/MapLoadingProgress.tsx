import { Loader2 } from 'lucide-react'
import { formatPointCount, parseMapLoadingDetail } from './mapLoadingProgress'
import './mapLoadingProgress.css'

type Props = { loading: boolean; message: string }

export function MapLoadingProgress({ loading, message }: Props) {
  if (!loading) return null
  const progress = parseMapLoadingDetail(message)
  const determinate = progress.completed !== null && progress.total !== null
  const percentage = determinate
    ? Math.floor(progress.completed! / progress.total! * 1000) / 10
    : null

  return (
    <div className="pcd-cloud-load-layer">
      <section className="pcd-cloud-load-card" aria-label="地图加载进度" aria-busy="true">
        <div className="pcd-cloud-load-heading" role="status" aria-live="polite">
          <Loader2 size={17} aria-hidden="true" />
          <strong>加载地图</strong>
          <span>{progress.label}</span>
        </div>
        {progress.filename ? (
          <div className="pcd-cloud-load-file" title={progress.filename}>{progress.filename}</div>
        ) : null}
        {progress.detail ? (
          <p className="pcd-cloud-load-detail" title={progress.detail}>{progress.detail}</p>
        ) : null}
        {determinate ? (
          <>
            <div className="pcd-cloud-load-metrics">
              <span>当前文件</span><strong>{percentage}%</strong>
            </div>
            <progress
              aria-label="当前文件点云整理进度"
              aria-valuetext={`${formatPointCount(progress.completed!)} / ${formatPointCount(progress.total!)} 点`}
              max={progress.total!} value={progress.completed!}
            />
            <div className="pcd-cloud-load-count">
              {formatPointCount(progress.completed!)} / {formatPointCount(progress.total!)} 点
            </div>
            {progress.completed === progress.total ? (
              <p className="pcd-cloud-load-note">当前文件已整理，正在完成地图加载</p>
            ) : null}
          </>
        ) : progress.completed !== null ? (
          <div className="pcd-cloud-load-count">已读取 {formatPointCount(progress.completed)} 点</div>
        ) : null}
      </section>
    </div>
  )
}
