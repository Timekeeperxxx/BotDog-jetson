import { useEffect, useState } from 'react'
import { ArrowRight, MapPinned } from 'lucide-react'
import { apiFetch } from '../../api/apiFetch'
import type { HealthResponse } from '../adminTypes'
import type { NavStateResponse } from '../../types/navState'
import { AdminCard, EmptyState, StatusBadge, ToolbarButton } from '../AdminUi'
import { useAuthState } from '../../stores/authStore'

type SafetyResponse = {
  safe_to_move: boolean
  reasons: string[]
  system_state: string
  control_adapter_ready: boolean
}

interface AdminControlPageProps {
  health: HealthResponse | null
  navState: NavStateResponse | null
  onOpenOperator: () => void
  onOpenPatrol: () => void
}

export function AdminControlPage({ health, navState, onOpenOperator, onOpenPatrol }: AdminControlPageProps) {
  const auth = useAuthState()
  const [safety, setSafety] = useState<SafetyResponse | null>(null)
  const [safetyError, setSafetyError] = useState<string | null>(null)
  const [safetyLoading, setSafetyLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    async function loadSafety() {
      setSafetyLoading(true)
      setSafetyError(null)
      try {
        const data = await apiFetch<SafetyResponse>('/api/v1/system/safety')
        if (!cancelled) setSafety(data)
      } catch (err) {
        if (!cancelled) {
          setSafety(null)
          setSafetyError(err instanceof Error ? err.message : '暂不可用')
        }
      } finally {
        if (!cancelled) setSafetyLoading(false)
      }
    }

    void loadSafety()

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-3">
        <AdminCard title="运行入口" subtitle="这里不直接下发控制命令，只保留进入操作台和导航页的快捷入口。">
          <div className="space-y-3">
            <ToolbarButton onClick={onOpenOperator}>
              <ArrowRight size={14} className="inline-block" /> 进入操作台
            </ToolbarButton>
            <ToolbarButton onClick={onOpenPatrol}>
              <MapPinned size={14} className="inline-block" /> 打开导航页
            </ToolbarButton>
          </div>
        </AdminCard>

        <AdminCard title="控制安全" subtitle="复用 /api/v1/system/safety 结果，明确显示当前能否移动。">
          {safetyError && <div className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{safetyError}</div>}
          {safetyLoading ? (
            <EmptyState title="安全状态加载中" description="正在拉取 /api/v1/system/safety 的当前结果。" />
          ) : safety ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-zinc-400">允许运动</span>
                <StatusBadge status={safety.safe_to_move ? 'normal' : 'failed'} />
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-zinc-400">系统状态</span>
                <span className="text-sm text-white">{safety.system_state}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-zinc-400">适配器就绪</span>
                <span className="text-sm text-white">{safety.control_adapter_ready ? '是' : '否'}</span>
              </div>
              <div>
                <div className="text-sm text-zinc-400">阻止原因</div>
                <div className="mt-2 text-sm text-zinc-200">
                  {safety.reasons.length > 0 ? safety.reasons.join('；') : '无'}
                </div>
              </div>
            </div>
          ) : (
            <EmptyState title="安全状态暂不可用" description="接口未返回数据时，这里只保留空状态，不伪造运动许可。" />
          )}
        </AdminCard>
      </div>

      <AdminCard title="控制边界说明" subtitle="第三阶段之前，这里只承接入口和状态，不重做控制链路。">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-2xl border border-white/8 bg-black/40 p-4">
            <div className="text-sm font-black text-white">当前用户</div>
            <div className="mt-2 text-sm text-zinc-300">{auth.username || '--'} · {auth.role || '--'}</div>
          </div>
          <div className="rounded-2xl border border-white/8 bg-black/40 p-4">
            <div className="text-sm font-black text-white">机器人状态</div>
            <div className="mt-2 text-sm text-zinc-300">
              {navState?.navigation_status?.status || '未知'} / {health?.status || '未知'}
            </div>
          </div>
        </div>
        <div className="mt-4 text-xs text-zinc-500">急停、导航和控制命令仍由现有运行时模块处理，这个页面只提供入口和状态总览。</div>
      </AdminCard>
    </div>
  )
}
