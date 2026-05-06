import { useMemo, useState } from 'react'
import { Copy, RefreshCw } from 'lucide-react'
import type { AdminLogEntry } from '../adminTypes'
import { AdminCard, EmptyState, SearchInput, TableCell, TableHead, ToolbarButton } from '../AdminUi'

export function AdminLogsPage({
  logs,
  loading,
  search,
  onSearchChange,
  onRefresh,
}: {
  logs: AdminLogEntry[]
  loading: boolean
  search: string
  onSearchChange: (value: string) => void
  onRefresh: () => void
}) {
  const [level, setLevel] = useState('ALL')

  const filteredLogs = useMemo(() => {
    return logs.filter((item) => {
      const keyword = search.toLowerCase()
      const hitKeyword = !keyword || `${item.module} ${item.message}`.toLowerCase().includes(keyword)
      const hitLevel = level === 'ALL' || item.level === level
      return hitKeyword && hitLevel
    })
  }, [logs, search, level])

  return (
    <AdminCard
      title="日志审计"
      subtitle="当前项目已提供 /api/v1/logs 最近日志查询；本页先做筛选、搜索、复制和刷新。"
      actions={
        <div className="flex flex-wrap items-center gap-3">
          <div className="w-72">
            <SearchInput value={search} onChange={onSearchChange} placeholder="搜索模块名或日志关键词" />
          </div>
          <select
            value={level}
            onChange={(event) => setLevel(event.target.value)}
            className="rounded-xl border border-white/10 bg-black/60 px-4 py-2.5 text-sm text-white outline-none focus:border-white/30"
          >
            <option value="ALL">全部等级</option>
            <option value="INFO">INFO</option>
            <option value="WARN">WARN</option>
            <option value="ERROR">ERROR</option>
            <option value="CRITICAL">CRITICAL</option>
          </select>
          <ToolbarButton onClick={onRefresh}><RefreshCw size={14} className="inline-block" /> 刷新</ToolbarButton>
        </div>
      }
    >
      {filteredLogs.length === 0 ? (
        <EmptyState title="暂无日志" description={loading ? '日志加载中。' : '当前没有匹配的日志记录。'} />
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead>
              <tr>
                <TableHead>时间</TableHead>
                <TableHead>等级</TableHead>
                <TableHead>模块</TableHead>
                <TableHead>消息</TableHead>
                <TableHead>操作</TableHead>
              </tr>
            </thead>
            <tbody>
              {filteredLogs.map((item) => (
                <tr key={item.log_id}>
                  <TableCell>{new Date(item.created_at).toLocaleString('zh-CN', { hour12: false })}</TableCell>
                  <TableCell>{item.level}</TableCell>
                  <TableCell>{item.module}</TableCell>
                  <TableCell className="max-w-[720px] break-all">{item.message}</TableCell>
                  <TableCell>
                    <ToolbarButton onClick={() => void navigator.clipboard.writeText(`${item.created_at} ${item.level} ${item.module} ${item.message}`)}>
                      <Copy size={14} className="inline-block" /> 复制
                    </ToolbarButton>
                  </TableCell>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-5 rounded-2xl border border-dashed border-white/10 bg-black/40 p-4 text-sm text-zinc-500">
        TODO：当前后端没有按时间区间、模块、等级分页检索的专门接口，也没有日志下载接口。本页先对现有最近日志结果做前端过滤。
      </div>
    </AdminCard>
  )
}
