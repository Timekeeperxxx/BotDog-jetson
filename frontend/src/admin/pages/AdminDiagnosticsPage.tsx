import { useState, type ReactNode } from 'react'
import { ExternalLink, FlaskConical, ServerCog } from 'lucide-react'
import { apiFetch } from '../../api/apiFetch'
import { AdminCard, EmptyState, ToolbarButton } from '../AdminUi'

export function AdminDiagnosticsPage({
  onOpenPatrol,
}: {
  onOpenPatrol: () => void
}) {
  const [loadingKey, setLoadingKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<unknown>(null)

  async function runDiagnostic(path: string) {
    setLoadingKey(path)
    setError(null)
    setResult(null)
    try {
      const data = await apiFetch(path)
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : '暂不可用')
    } finally {
      setLoadingKey(null)
    }
  }

  return (
    <div className="space-y-6">
      <AdminCard title="诊断工具" subtitle="这里只放可验证的排查入口，不伪造未实现的诊断面板。">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <DiagTile
            icon={<ServerCog size={14} />}
            title="/api/v1/system/safety"
            desc="检查当前是否允许运动，以及阻止原因。"
            onClick={() => void runDiagnostic('/api/v1/system/safety')}
            loading={loadingKey === '/api/v1/system/safety'}
          />
          <DiagTile
            icon={<FlaskConical size={14} />}
            title="/api/v1/auth/status"
            desc="检查当前登录态和角色信息。"
            onClick={() => void runDiagnostic('/api/v1/auth/status')}
            loading={loadingKey === '/api/v1/auth/status'}
          />
        </div>
      </AdminCard>

      <AdminCard title="快捷入口" subtitle="用于现场排障，不替代正式后台流程。">
        <div className="flex flex-wrap gap-3">
          <ToolbarButton onClick={onOpenPatrol}><ExternalLink size={14} className="inline-block" /> 打开导航页</ToolbarButton>
          <ToolbarButton onClick={() => void runDiagnostic('/api/v1/system/safety')}>检查安全接口</ToolbarButton>
          <ToolbarButton onClick={() => void runDiagnostic('/api/v1/auth/status')}>检查登录状态</ToolbarButton>
        </div>
      </AdminCard>

      <AdminCard title="诊断结果" subtitle="按钮触发后，直接在当前页面查看 JSON 返回。">
        {error ? <div className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{error}</div> : null}
        {!error && loadingKey ? (
          <EmptyState title="诊断中" description={`正在请求 ${loadingKey}，请稍候。`} />
        ) : null}
        {!error && !loadingKey && result != null ? (
          <pre className="overflow-x-auto rounded-2xl border border-white/8 bg-black/60 p-4 text-xs leading-6 text-zinc-200">
            {JSON.stringify(result, null, 2)}
          </pre>
        ) : null}
        {!error && !loadingKey && result == null ? (
          <EmptyState title="等待诊断操作" description="点击上方按钮后，这里会显示 pretty print 的 JSON 结果或错误信息。" />
        ) : null}
      </AdminCard>

      <AdminCard title="说明" subtitle="第三阶段先把壳拆清楚，后续再补更细的诊断能力。">
        <EmptyState
          title="暂未接入完整诊断面板"
          description="如果后续要做网络、磁盘、进程和 ROS 通道健康检查，可以再补专门的诊断 API 和独立页面。"
        />
      </AdminCard>
    </div>
  )
}

function DiagTile({
  icon,
  title,
  desc,
  onClick,
  loading = false,
}: {
  icon: ReactNode
  title: string
  desc: string
  onClick?: () => void
  loading?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-2xl border border-white/10 bg-black/50 p-4 text-left transition-all hover:border-white/20 hover:bg-white/5"
    >
      <div className="flex items-center gap-2 text-white">
        {icon}
        <span className="text-sm font-black">{loading ? '加载中…' : title}</span>
      </div>
      <div className="mt-3 text-sm text-zinc-400">{desc}</div>
    </button>
  )
}
