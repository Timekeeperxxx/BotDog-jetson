import { useCallback, useEffect, useMemo, useState } from 'react'
import { Copy, RefreshCw } from 'lucide-react'
import { getLogFileTail, listLogFiles } from '../adminApi'
import type { AdminLogEntry, AdminLogFileInfo, AdminLogFileTail } from '../adminTypes'
import { AdminCard, EmptyState, SearchInput, TableCell, TableHead, ToolbarButton } from '../AdminUi'

const CATEGORY_TABS = [
  { key: 'ALL', label: '全部' },
  { key: 'auth', label: '登录', keywords: ['auth.login', 'action=auth.login', '登录', 'login', 'auth.status'] },
  { key: 'control', label: '控制', keywords: ['control.', '控制', '手动控制', 'control_service'] },
  { key: 'nav', label: '导航', keywords: ['nav.', '导航', 'go-to', 'go_to', 'nav.go_to', 'nav.e_stop'] },
  { key: 'config', label: '配置', keywords: ['config.', '配置', '参数'] },
  { key: 'delete', label: '删除', keywords: ['delete', '删除', '.delete', 'soft delete', '软删除'] },
  { key: 'estop', label: '急停', keywords: ['e_stop', '急停', 'E_STOP', 'stop'] },
  { key: 'permission', label: '权限', keywords: ['permission', '403', '权限', '缺少访问令牌', 'token 已失效', 'token失效'] },
  { key: 'fail', label: '失败', keywords: ['result=fail', 'failed', 'error', 'critical', '失败', '异常'] },
] as const

type CategoryKey = typeof CATEGORY_TABS[number]['key']
type LogTab = 'audit' | 'runtime'

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

function formatBytes(value: number) {
  if (!Number.isFinite(value)) return '--'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

function formatModifiedAt(value: string) {
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return value
  return new Date(time).toLocaleString('zh-CN', { hour12: false })
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
  const [tab, setTab] = useState<LogTab>('audit')
  const [level, setLevel] = useState('ALL')
  const [category, setCategory] = useState<CategoryKey>('ALL')

  const [runtimeFiles, setRuntimeFiles] = useState<AdminLogFileInfo[]>([])
  const [runtimeFileName, setRuntimeFileName] = useState('backend.log')
  const [runtimeLines, setRuntimeLines] = useState(300)
  const [runtimeFilesLoading, setRuntimeFilesLoading] = useState(false)
  const [runtimeFilesError, setRuntimeFilesError] = useState<string | null>(null)
  const [runtimeTailLoading, setRuntimeTailLoading] = useState(false)
  const [runtimeTailError, setRuntimeTailError] = useState<string | null>(null)
  const [runtimeTail, setRuntimeTail] = useState<AdminLogFileTail | null>(null)

  const filteredLogs = useMemo(() => {
    return logs.filter((item) => {
      const keyword = search.toLowerCase()
      const hitKeyword = !keyword || `${item.module} ${item.message}`.toLowerCase().includes(keyword)
      const hitLevel = level === 'ALL' || item.level === level
      const hitCategory = matchCategory(item, category)
      return hitKeyword && hitLevel && hitCategory
    })
  }, [logs, search, level, category])

  const refreshRuntimeFiles = useCallback(async () => {
    setRuntimeFilesLoading(true)
    setRuntimeFilesError(null)
    try {
      const data = await listLogFiles()
      const nextFiles = Array.isArray(data.items) ? data.items : []
      setRuntimeFiles(nextFiles)
      if (nextFiles.length === 0) {
        setRuntimeTail(null)
        setRuntimeTailError(null)
        return
      }

      setRuntimeFileName((current) => (
        nextFiles.some((item) => item.name === current) ? current : nextFiles[0].name
      ))
    } catch (error) {
      setRuntimeFiles([])
      setRuntimeTail(null)
      setRuntimeFilesError(error instanceof Error ? error.message : '后端运行日志列表加载失败')
    } finally {
      setRuntimeFilesLoading(false)
    }
  }, [])

  const refreshRuntimeTail = useCallback(async (name: string, nextLines = runtimeLines) => {
    if (!name) return
    setRuntimeTailLoading(true)
    setRuntimeTailError(null)
    try {
      const data = await getLogFileTail(name, nextLines)
      setRuntimeTail(data)
    } catch (error) {
      setRuntimeTail(null)
      setRuntimeTailError(error instanceof Error ? error.message : '后端运行日志读取失败')
    } finally {
      setRuntimeTailLoading(false)
    }
  }, [runtimeLines])

  useEffect(() => {
    if (tab !== 'runtime') return
    void refreshRuntimeFiles()
  }, [refreshRuntimeFiles, tab])

  useEffect(() => {
    if (tab !== 'runtime') return
    if (runtimeFiles.length === 0) return
    if (!runtimeFiles.some((item) => item.name === runtimeFileName)) return
    void refreshRuntimeTail(runtimeFileName, runtimeLines)
  }, [refreshRuntimeTail, runtimeFileName, runtimeFiles, runtimeLines, tab])

  const runtimeFileInfo = useMemo(
    () => runtimeFiles.find((item) => item.name === runtimeFileName) ?? null,
    [runtimeFileName, runtimeFiles],
  )

  return (
    <div className="space-y-6">
      <AdminCard
        title="日志中心"
        subtitle="审计日志来自 operation_logs；后端运行日志来自 logs/*.log 与 logs/scripts/*.log，二者分开查看。"
      >
        <div className="flex flex-wrap gap-3">
          <LogTabButton active={tab === 'audit'} label="审计日志" onClick={() => setTab('audit')} />
          <LogTabButton active={tab === 'runtime'} label="后端运行日志" onClick={() => setTab('runtime')} />
        </div>
      </AdminCard>

      {tab === 'audit' ? (
        <AdminCard
          title="审计日志"
          subtitle="这里显示 operation_logs 审计表中的用户操作、接口访问和关键业务事件，不是完整的后端运行输出。"
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
          <div className="mb-4 flex flex-wrap gap-1.5">
            {CATEGORY_TABS.map((item) => (
              <button
                key={item.key}
                onClick={() => setCategory(item.key)}
                className={`rounded-lg border px-3 py-1.5 text-[10px] font-black uppercase tracking-[0.15em] transition-all ${
                  category === item.key
                    ? 'border-white/30 bg-white/10 text-white'
                    : 'border-white/10 text-zinc-400 hover:border-white/20 hover:text-zinc-200'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          {filteredLogs.length === 0 ? (
            <EmptyState title="暂无审计日志" description={loading ? '审计日志加载中。' : '当前没有匹配的日志记录。'} />
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
                          <span
                            className={`text-[10px] font-black uppercase tracking-wider ${
                              item.level === 'CRITICAL'
                                ? 'text-red-400'
                                : item.level === 'ERROR'
                                  ? 'text-red-300'
                                  : item.level === 'WARN'
                                    ? 'text-amber-300'
                                    : 'text-zinc-400'
                            }`}
                          >
                            {item.level}
                          </span>
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
            审计日志用于记录用户操作、接口请求和关键业务事件，便于追责和排查，但不等同于完整的服务运行日志。
          </div>
        </AdminCard>
      ) : (
        <AdminCard
          title="后端运行日志"
          subtitle="读取 logs 目录下的运行日志文件，便于直接查看后端、访问和脚本输出。"
          actions={
            <div className="flex flex-wrap items-center gap-3">
              <ToolbarButton onClick={() => void refreshRuntimeFiles()}>
                <RefreshCw size={14} className="inline-block" /> 刷新
              </ToolbarButton>
            </div>
          }
        >
          <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
            <div className="space-y-4">
              <div className="rounded-2xl border border-white/8 bg-black/40 p-4">
                <div className="text-[10px] font-black uppercase tracking-[0.2em] text-zinc-500">日志文件</div>
                <div className="mt-3">
                  <select
                    value={runtimeFileName}
                    onChange={(event) => setRuntimeFileName(event.target.value)}
                    className="w-full rounded-xl border border-white/10 bg-black/60 px-4 py-2.5 text-sm text-white outline-none focus:border-white/30"
                  >
                    {runtimeFiles.length === 0 ? (
                      <option value="">暂无可查看日志</option>
                    ) : (
                      runtimeFiles.map((item) => (
                        <option key={item.name} value={item.name}>
                          {item.name}
                        </option>
                      ))
                    )}
                  </select>
                </div>
                <div className="mt-4 space-y-2 text-sm text-zinc-300">
                  <div>文件大小：{runtimeFileInfo ? formatBytes(runtimeFileInfo.size_bytes) : '--'}</div>
                  <div>更新时间：{runtimeFileInfo ? formatModifiedAt(runtimeFileInfo.modified_at) : '--'}</div>
                  <div>行数提示：{runtimeFileInfo?.lines_hint != null ? runtimeFileInfo.lines_hint : '--'}</div>
                </div>
                {runtimeFilesLoading ? <div className="mt-3 text-xs text-zinc-500">日志文件列表加载中…</div> : null}
                {runtimeFilesError ? <div className="mt-3 rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{runtimeFilesError}</div> : null}
              </div>

              <div className="rounded-2xl border border-white/8 bg-black/40 p-4">
                <div className="text-[10px] font-black uppercase tracking-[0.2em] text-zinc-500">尾部行数</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {[100, 300, 500, 1000].map((value) => (
                    <ToolbarButton
                      key={value}
                      onClick={() => setRuntimeLines(value)}
                      disabled={runtimeLines === value}
                    >
                      {value}
                    </ToolbarButton>
                  ))}
                </div>
                <div className="mt-3 text-xs text-zinc-500">默认展示最近 300 行，可根据排障需要切换。</div>
              </div>
            </div>

            <div className="rounded-2xl border border-white/8 bg-black/40 p-4">
              <div className="flex items-center justify-between gap-3 border-b border-white/8 pb-3">
                <div>
                  <div className="text-sm font-black text-white">{runtimeFileName || '未选择日志文件'}</div>
                  <div className="mt-1 text-xs text-zinc-500">
                    {runtimeTail ? `最近 ${runtimeTail.line_count} 行${runtimeTail.truncated ? '（已截断）' : ''}` : '读取后端运行日志尾部内容'}
                  </div>
                </div>
              </div>

              {runtimeTailLoading ? (
                <EmptyState title="日志加载中" description="正在读取日志文件尾部内容。" />
              ) : runtimeTailError ? (
                <div className="mt-4 rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
                  {runtimeTailError}
                </div>
              ) : runtimeFilesLoading ? (
                <EmptyState title="日志文件加载中" description="正在读取 logs 目录下可查看的运行日志文件。" />
              ) : runtimeFiles.length === 0 ? (
                <EmptyState title="暂无可查看的运行日志" description="logs 目录中没有符合白名单的日志文件，或当前文件列表为空。" />
              ) : runtimeTail && runtimeTail.lines.length > 0 ? (
                <pre className="mt-4 max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-2xl border border-white/8 bg-black/80 p-4 font-mono text-[11px] leading-6 text-zinc-200">
                  {runtimeTail.lines.join('\n')}
                </pre>
              ) : (
                <EmptyState
                  title="日志内容为空"
                  description="目标日志文件当前没有可展示的内容，或文件尚未写入。"
                />
              )}

              {runtimeTail && runtimeTail.truncated ? (
                <div className="mt-3 text-xs text-amber-300">
                  仅展示最近 {runtimeTail.line_count} 行，完整日志请查看服务器上的原始文件。
                </div>
              ) : null}
            </div>
          </div>
        </AdminCard>
      )}
    </div>
  )
}

function LogTabButton({
  active,
  label,
  onClick,
}: {
  active: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-xl border px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] transition-all ${
        active
          ? 'border-white/30 bg-white/10 text-white'
          : 'border-white/10 text-zinc-400 hover:border-white/20 hover:bg-white/5 hover:text-zinc-200'
      }`}
    >
      {label}
    </button>
  )
}
