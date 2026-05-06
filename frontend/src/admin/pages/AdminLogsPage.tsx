import { useMemo, useState } from 'react'
import { Copy, RefreshCw } from 'lucide-react'
import type { AdminLogEntry } from '../adminTypes'
import { AdminCard, EmptyState, SearchInput, TableCell, TableHead, ToolbarButton } from '../AdminUi'

// 类别筛选定义：同时支持英文结构化关键词和中文关键词
const CATEGORY_TABS = [
  { key: 'ALL', label: '全部' },
  {
    key: 'auth', label: '登录',
    keywords: ['auth.login', 'action=auth.login', '登录', 'login', 'auth.status'],
  },
  {
    key: 'control', label: '控制',
    keywords: ['control.', '控制', '手动控制', 'control_service'],
  },
  {
    key: 'nav', label: '导航',
    keywords: ['nav.', '导航', 'go-to', 'go_to', 'nav.go_to', 'nav.e_stop', 'current_goal'],
  },
  {
    key: 'config', label: '配置',
    keywords: ['config.', '配置', '参数'],
  },
  {
    key: 'delete', label: '删除',
    keywords: ['delete', '删除', '.delete', 'soft delete', '软删除'],
  },
  {
    key: 'estop', label: '急停',
    keywords: ['e_stop', '急停', 'E_STOP', 'stop'],
  },
  {
    key: 'permission', label: '权限',
    keywords: ['permission', '403', '权限', '缺少访问令牌', 'token 已失效', 'token失效'],
  },
  {
    key: 'fail', label: '失败',
    keywords: ['result=fail', 'failed', 'error', 'critical', '失败', '异常'],
  },
] as const

type CategoryKey = typeof CATEGORY_TABS[number]['key']

function isHighRisk(item: AdminLogEntry): boolean {
  if (item.level === 'ERROR' || item.level === 'CRITICAL') return true
  if (item.level === 'WARN') {
    const msg = item.message.toLowerCase()
    return msg.includes('result=fail') || msg.includes('e_stop') || msg.includes('失败') || msg.includes('异常')
  }
  return false
}

function matchCategory(item: AdminLogEntry, cat: CategoryKey): boolean {
  if (cat === 'ALL') return true
  const tab = CATEGORY_TABS.find((t) => t.key === cat)
  if (!tab || !('keywords' in tab)) return true
  const text = `${item.module} ${item.message}`.toLowerCase()
  return tab.keywords.some((kw) => text.includes(kw.toLowerCase()))
}

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
  const [category, setCategory] = useState<CategoryKey>('ALL')

  const filteredLogs = useMemo(() => {
    return logs.filter((item) => {
      const keyword = search.toLowerCase()
      const hitKeyword = !keyword || `${item.module} ${item.message}`.toLowerCase().includes(keyword)
      const hitLevel = level === 'ALL' || item.level === level
      const hitCategory = matchCategory(item, category)
      return hitKeyword && hitLevel && hitCategory
    })
  }, [logs, search, level, category])

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
      {/* 类别快捷 Tab */}
      <div className="mb-4 flex flex-wrap gap-1.5">
        {CATEGORY_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setCategory(tab.key)}
            className={`rounded-lg border px-3 py-1.5 text-[10px] font-black uppercase tracking-[0.15em] transition-all ${
              category === tab.key
                ? 'border-white/30 bg-white/10 text-white'
                : 'border-white/10 text-zinc-400 hover:border-white/20 hover:text-zinc-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

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
              {filteredLogs.map((item) => {
                const highRisk = isHighRisk(item)
                return (
                  <tr
                    key={item.log_id}
                    className={highRisk ? 'border-l-4 border-red-500/80 bg-red-500/10' : ''}
                  >
                    <TableCell>{new Date(item.created_at).toLocaleString('zh-CN', { hour12: false })}</TableCell>
                    <TableCell>
                      <span className={`text-[10px] font-black uppercase tracking-wider ${
                        item.level === 'CRITICAL' ? 'text-red-400' :
                        item.level === 'ERROR' ? 'text-red-300' :
                        item.level === 'WARN' ? 'text-amber-300' :
                        'text-zinc-400'
                      }`}>{item.level}</span>
                    </TableCell>
                    <TableCell>{item.module}</TableCell>
                    <TableCell className="max-w-[720px] break-all">{item.message}</TableCell>
                    <TableCell>
                      <ToolbarButton onClick={() => void navigator.clipboard.writeText(`${item.created_at} ${item.level} ${item.module} ${item.message}`)}>
                        <Copy size={14} className="inline-block" /> 复制
                      </ToolbarButton>
                    </TableCell>
                  </tr>
                )
              })}
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
