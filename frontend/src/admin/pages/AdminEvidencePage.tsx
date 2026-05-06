import { useMemo, useState } from 'react'
import { Download, Eye, RefreshCw, Trash2 } from 'lucide-react'
import type { EvidenceItem } from '../../types/evidence'
import { getApiUrl } from '../../config/api'
import { AdminCard, ConfirmDialog, EmptyState, SearchInput, StatusBadge, TableCell, TableHead, ToolbarButton } from '../AdminUi'
import { hasAuthSession, hasRole, useAuthState } from '../../stores/authStore'

function getEvidenceUrl(item: EvidenceItem) {
  if (!item.image_url) return null
  if (item.image_url.startsWith('http://') || item.image_url.startsWith('https://')) return item.image_url
  return getApiUrl(item.image_url)
}

export function AdminEvidencePage({
  evidence,
  loading,
  search,
  onSearchChange,
  onRefresh,
  onDelete,
}: {
  evidence: EvidenceItem[]
  loading: boolean
  search: string
  onSearchChange: (value: string) => void
  onRefresh: () => void
  onDelete: (item: EvidenceItem) => Promise<void>
}) {
  useAuthState()
  const canAdmin = hasAuthSession() && hasRole('admin')
  const [severity, setSeverity] = useState('ALL')
  const [confirmItem, setConfirmItem] = useState<EvidenceItem | null>(null)
  const [previewItem, setPreviewItem] = useState<EvidenceItem | null>(null)

  const filteredEvidence = useMemo(() => {
    return evidence.filter((item) => {
      const keyword = search.toLowerCase()
      const hitKeyword = !keyword || `${item.message || ''} ${item.event_type} ${item.event_code || ''}`.toLowerCase().includes(keyword)
      const hitSeverity = severity === 'ALL' || item.severity === severity
      return hitKeyword && hitSeverity
    })
  }, [evidence, search, severity])

  return (
    <div className="space-y-6">
      <AdminCard
        title="证据库"
        subtitle="支持筛选、搜索、刷新；删除前必须二次确认。"
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <div className="w-72">
              <SearchInput value={search} onChange={onSearchChange} placeholder="搜索事件类型 / 告警文案 / event_code" />
            </div>
            <select
              value={severity}
              onChange={(event) => setSeverity(event.target.value)}
              className="rounded-xl border border-white/10 bg-black/60 px-4 py-2.5 text-sm text-white outline-none focus:border-white/30"
            >
              <option value="ALL">全部等级</option>
              <option value="INFO">INFO</option>
              <option value="WARNING">WARNING</option>
              <option value="CRITICAL">CRITICAL</option>
            </select>
            <ToolbarButton onClick={onRefresh}><RefreshCw size={14} className="inline-block" /> 刷新</ToolbarButton>
          </div>
        }
      >
        {filteredEvidence.length === 0 ? (
          <EmptyState title="暂无证据" description={loading ? '证据列表加载中。' : '当前没有匹配的证据记录。'} />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr>
                  <TableHead>时间</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>等级</TableHead>
                  <TableHead>消息</TableHead>
                  <TableHead>置信度</TableHead>
                  <TableHead>文件</TableHead>
                  <TableHead>操作</TableHead>
                </tr>
              </thead>
              <tbody>
                {filteredEvidence.map((item) => (
                  <tr key={item.evidence_id}>
                    <TableCell>{new Date(item.created_at).toLocaleString('zh-CN', { hour12: false })}</TableCell>
                    <TableCell>{item.event_type}</TableCell>
                    <TableCell><StatusBadge status={item.severity === 'CRITICAL' ? 'failed' : item.severity === 'WARNING' ? 'degraded' : 'normal'} /></TableCell>
                    <TableCell>
                      <div>{item.message || '--'}</div>
                      <div className="mt-1 text-xs text-zinc-500">{item.event_code || '--'}</div>
                    </TableCell>
                    <TableCell>{item.confidence != null ? `${(item.confidence * 100).toFixed(1)}%` : '--'}</TableCell>
                    <TableCell className="max-w-[260px] break-all text-xs text-zinc-400">{item.file_path || '--'}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-2">
                        <ToolbarButton onClick={() => setPreviewItem(item)}><Eye size={14} className="inline-block" /> 详情</ToolbarButton>
                        {getEvidenceUrl(item) ? (
                          <a
                            href={getEvidenceUrl(item) || '#'}
                            target="_blank"
                            rel="noreferrer"
                            className="rounded-xl border border-white/12 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-white transition-all hover:border-white/30 hover:bg-white/5"
                          >
                            <Download size={14} className="mr-1 inline-block" /> 打开
                          </a>
                        ) : null}
                        {canAdmin ? (
                          <ToolbarButton danger onClick={() => setConfirmItem(item)}><Trash2 size={14} className="inline-block" /> 删除</ToolbarButton>
                        ) : null}
                      </div>
                    </TableCell>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </AdminCard>

      <ConfirmDialog
        open={confirmItem !== null}
        title="确认删除证据"
        description={confirmItem ? `即将删除证据 #${confirmItem.evidence_id}，该操作不可恢复。` : ''}
        confirmText="确认删除"
        onCancel={() => setConfirmItem(null)}
        onConfirm={() => {
          if (!confirmItem) return
          void onDelete(confirmItem)
          setConfirmItem(null)
        }}
        danger
      />

      <ConfirmDialog
        open={previewItem !== null}
        title={previewItem?.message || previewItem?.event_type || '证据详情'}
        description={previewItem ? [
          `事件类型：${previewItem.event_type}`,
          `事件代码：${previewItem.event_code || '--'}`,
          `等级：${previewItem.severity}`,
          `置信度：${previewItem.confidence != null ? `${(previewItem.confidence * 100).toFixed(1)}%` : '--'}`,
          `文件路径：${previewItem.file_path || '--'}`,
          `时间：${new Date(previewItem.created_at).toLocaleString('zh-CN', { hour12: false })}`,
          '说明：当前后端只提供证据列表和删除能力，证据上下文详情仍需后续补充专门接口。',
        ].join('\n') : ''}
        confirmText="关闭"
        onCancel={() => setPreviewItem(null)}
        onConfirm={() => setPreviewItem(null)}
      />
    </div>
  )
}
