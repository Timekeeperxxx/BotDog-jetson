import { useEffect, useId, useRef, useState } from 'react'
import { AlertTriangle, ChevronUp, LoaderCircle, X } from 'lucide-react'
import type { MappingControlResponse } from '../../types/pcdMap'
import './mappingSaveProgress.css'

type Props = {
  status: MappingControlResponse | null
  connectionError: string | null
  operationError?: { title: string; message: string } | null
}

export function formatSaveTime(seconds: number): string {
  const whole = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0))
  return `${Math.floor(whole / 60)}分${String(whole % 60).padStart(2, '0')}秒`
}

export function MappingSaveProgress({ status, connectionError, operationError = null }: Props) {
  const [receivedAt, setReceivedAt] = useState(() => performance.now())
  const [tick, setTick] = useState(() => performance.now())
  const [detailsOpen, setDetailsOpen] = useState(false)
  const detailsId = useId()
  const containerRef = useRef<HTMLElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  useEffect(() => { setReceivedAt(performance.now()) }, [status])
  useEffect(() => {
    const timer = window.setInterval(() => setTick(performance.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  useEffect(() => {
    if (!detailsOpen) return
    dialogRef.current?.focus()
    const dismissOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !containerRef.current?.contains(event.target)) {
        setDetailsOpen(false)
      }
    }
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && containerRef.current?.contains(document.activeElement)) {
        event.preventDefault()
        setDetailsOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('pointerdown', dismissOutside)
    document.addEventListener('keydown', dismissOnEscape)
    return () => {
      document.removeEventListener('pointerdown', dismissOutside)
      document.removeEventListener('keydown', dismissOnEscape)
    }
  }, [detailsOpen])

  const extra = Math.max(0, (tick - receivedAt) / 1000)
  const progress = status?.save_progress
  const completed = progress?.completed
  const total = progress?.total
  const measurable = typeof completed === 'number' && typeof total === 'number'
    && Number.isSafeInteger(completed) && Number.isSafeInteger(total)
    && completed >= 0 && total > 0 && completed <= total
  const unit = progress?.unit || '项'
  const age = progress?.update_age_seconds
  const stale = age != null && age + extra > 60
  const warning = Boolean(connectionError) || stale
  const label = progress?.label || '等待保存开始'
  const detail = progress?.detail || (progress?.stage && progress.stage !== 'stopping'
    ? '后台正在处理当前阶段。'
    : '已请求结束建图，正在等待后台报告保存阶段。')
  const elapsed = formatSaveTime((status?.save_elapsed_seconds ?? 0) + extra)
  const stageElapsed = formatSaveTime((progress?.stage_elapsed_seconds ?? 0) + extra)

  return (
    <section
      ref={containerRef}
      className={`pcd-save-progress ${warning ? 'has-warning' : ''} ${operationError ? 'has-error' : ''}`}
      aria-label="地图保存进度"
    >
      {operationError ? (
        <p className="pcd-save-operation-error" role="alert">
          <strong>{operationError.title}</strong>：{operationError.message}
        </p>
      ) : null}
      <div className="pcd-save-summary">
        <div className="pcd-save-stage" aria-live="polite" aria-atomic="true">
          {warning ? <AlertTriangle size={15} aria-hidden="true" /> : <LoaderCircle size={15} className="pcd-spin" aria-hidden="true" />}
          <span className="pcd-save-badge" role={warning ? 'status' : undefined}>
            {connectionError ? '正在重连' : stale ? '进度待更新' : '保存中'}
          </span>
          <strong title={label}>{label}</strong>
        </div>
        <span className="pcd-save-elapsed" aria-label={`保存已用 ${elapsed}`}>
          <span>已用</span> {elapsed}
        </span>
        {measurable ? (
          <div className="pcd-save-meter" title={`${warning ? '上次记录的' : '当前阶段'}${unit}：${completed} / ${total}`}>
            <span aria-label={`当前阶段${unit}：${completed} / ${total}`}>{completed} / {total}</span>
            <progress aria-label={`当前阶段${unit}处理进度`} value={completed} max={total} />
          </div>
        ) : null}
        <button
          ref={triggerRef}
          type="button"
          className="pcd-save-details-toggle"
          aria-label="查看保存详情"
          aria-expanded={detailsOpen}
          aria-controls={detailsId}
          onClick={() => setDetailsOpen(value => !value)}
        >
          详情 <ChevronUp size={13} aria-hidden="true" />
        </button>
      </div>
      {detailsOpen ? (
        <div
          ref={dialogRef}
          id={detailsId}
          className="pcd-save-details"
          role="dialog"
          aria-label="地图保存详情"
          tabIndex={-1}
        >
          <div className="pcd-save-details-heading">
            <strong>地图保存详情</strong>
            <button type="button" aria-label="关闭保存详情" onClick={() => {
              setDetailsOpen(false)
              triggerRef.current?.focus()
            }}><X size={16} aria-hidden="true" /></button>
          </div>
          <p className="pcd-save-scene">{status?.scene_name || '当前场景'}</p>
          <p>{label} · {detail}</p>
          <dl className="pcd-save-details-meta">
            <dt>保存已用</dt><dd>{elapsed}</dd>
            <dt>当前阶段已用</dt><dd>{stageElapsed}</dd>
            <dt>当前阶段进度</dt>
            <dd>{measurable ? `${completed} / ${total} ${unit}` : '此阶段没有可靠总量，不估算完成百分比。'}</dd>
            <dt>最近进度</dt>
            <dd>{age != null ? age + extra < 2 ? '刚刚' : formatSaveTime(age + extra) + '前' : '等待首次进度'}</dd>
          </dl>
          {!connectionError && status?.save_worker_alive != null ? (
            <p>{status.save_worker_alive ? '保存进程仍在运行' : '保存进程已退出，正在确认结果'}</p>
          ) : null}
          {connectionError ? <p className="pcd-save-warning" role="status">{connectionError}</p> : null}
          {!connectionError && stale ? (
            <p className="pcd-save-warning">暂未收到新的工作进度，尚不能确认保存结果。</p>
          ) : null}
          <p className="pcd-save-safety">
            {progress?.baseline_saved ? '基础文件已写入，最终优化与验收尚未结束。' : '正在保存本次采集的数据。'}
            {' '}完成前请勿关闭设备或使用该场景导航。刷新页面后会恢复保存状态。
          </p>
        </div>
      ) : null}
    </section>
  )
}
