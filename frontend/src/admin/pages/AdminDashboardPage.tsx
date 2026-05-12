import { useMemo, type ReactNode } from 'react'
import { ArrowRight, Bot, Database, LayoutDashboard, RefreshCw } from 'lucide-react'
import type { AdminDashboardData, AdminSection, ModuleHealthState } from '../adminTypes'
import { mapHealthStatus, mapNavStatus } from '../adminTypes'
import { AdminCard, StatusBadge } from '../AdminUi'

function formatRelativeTime(value?: string | null) {
  if (!value) return '--'
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return value
  const diff = Math.max(0, Date.now() - time)
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

type DashboardCard = {
  title: string
  status: ModuleHealthState
  summary: string
  source: string
}

type DashboardEvent = {
  title: string
  detail: string
  time: string
  status: ModuleHealthState
}

export function AdminDashboardPage({
  data,
  onSectionChange,
  onRefresh,
}: {
  data: AdminDashboardData
  onSectionChange: (section: AdminSection) => void
  onRefresh: () => void
}) {
  const statusCards = useMemo<DashboardCard[]>(() => {
    const enabledVideos = data.videoSources.filter((item) => item.enabled).length
    return [
      {
        title: '后端服务状态',
        status: mapHealthStatus(data.health?.status),
        summary: data.health ? `当前状态：${data.health.status}，运行时长 ${formatUptime(data.health.uptime)}` : '未获取到后端健康状态。',
        source: '来源 /api/v1/system/health',
      },
      {
        title: '导航定位状态',
        status: mapNavStatus(data.navState?.navigation_status.status),
        summary: data.navState
          ? `定位 ${data.navState.localization_status.status} · 导航 ${data.navState.navigation_status.status}`
          : '未获取到导航状态。',
        source: '来源 nav.websocket / system.nav_state',
      },
      {
        title: '视频源状态',
        status: enabledVideos > 0 ? 'normal' : 'waiting',
        summary: enabledVideos > 0 ? `已启用 ${enabledVideos} 路视频源。` : '当前没有启用的视频源。',
        source: '来源 /api/v1/admin/video-sources',
      },
      {
        title: '机器人控制状态',
        status: data.health?.mavlink_connected ? 'normal' : 'degraded',
        summary: data.health?.mavlink_connected ? '控制链路在线。' : '控制链路暂未确认。',
        source: '来源 /api/v1/system/health',
      },
    ]
  }, [data.health, data.navState, data.videoSources])

  const recentEvents = useMemo<DashboardEvent[]>(() => {
    const navStatus = data.navState?.navigation_status
    const navEvent = navStatus
      ? {
          title: '导航状态',
          detail: navStatus.message || `${navStatus.status}${navStatus.target_name ? ` · ${navStatus.target_name}` : ''}`,
          time: formatRelativeTime(navStatus.timestamp ? new Date(navStatus.timestamp * 1000).toISOString() : null),
          status: mapNavStatus(navStatus.status),
        }
      : null

    const latestErrorLog = data.logs.find((item) => ['ERROR', 'CRITICAL'].includes(item.level))
    const latestAlert = data.alerts[0]
    const latestOperationLog = data.logs[0]
    const latestEvidence = data.evidence[0]

    return [
      latestErrorLog ? { title: '最新错误', detail: `${latestErrorLog.module} · ${latestErrorLog.message}`, time: formatRelativeTime(latestErrorLog.created_at), status: 'failed' } : null,
      latestAlert ? { title: '最新告警', detail: latestAlert.message || latestAlert.event_type, time: formatRelativeTime(latestAlert.timestamp), status: latestAlert.severity === 'CRITICAL' ? 'failed' : 'degraded' } : null,
      navEvent,
      latestOperationLog ? { title: '最新操作日志', detail: `${latestOperationLog.module} · ${latestOperationLog.message}`, time: formatRelativeTime(latestOperationLog.created_at), status: latestOperationLog.level === 'ERROR' || latestOperationLog.level === 'CRITICAL' ? 'failed' : 'waiting' } : null,
      latestEvidence ? { title: '最新证据', detail: latestEvidence.message || latestEvidence.event_type, time: formatRelativeTime(latestEvidence.created_at), status: latestEvidence.severity === 'CRITICAL' ? 'failed' : 'degraded' } : null,
    ].filter((item): item is DashboardEvent => item !== null)
  }, [data.alerts, data.evidence, data.logs, data.navState])

  return (
    <div className="space-y-6">
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {statusCards.map((card) => (
          <div key={card.title} className="rounded-3xl border border-white/8 bg-black/40 p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="text-sm font-medium text-white">{card.title}</div>
              <StatusBadge status={card.status} />
            </div>
            <div className="mt-4 text-sm leading-6 text-zinc-200">{card.summary}</div>
            <div className="mt-3 text-xs text-zinc-500">{card.source}</div>
          </div>
        ))}
      </section>

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <AdminCard title="快捷操作" subtitle="优先保留现场最常用的入口。">
          <div className="grid gap-3 sm:grid-cols-2">
            <ActionButton icon={<LayoutDashboard size={16} />} onClick={() => onSectionChange('navigation')}>打开导航管理</ActionButton>
            <ActionButton icon={<Bot size={16} />} onClick={() => window.location.assign('/operator')}>打开操作端</ActionButton>
            <ActionButton icon={<RefreshCw size={16} />} onClick={onRefresh}>刷新后台数据</ActionButton>
            <ActionButton icon={<Database size={16} />} onClick={() => onSectionChange('logs')}>查看后端日志</ActionButton>
            <ActionButton icon={<ArrowRight size={16} />} onClick={() => onSectionChange('config')}>打开系统配置</ActionButton>
          </div>
        </AdminCard>

        <AdminCard title="最近事件" subtitle="只保留现场最关心的 5 条信息。">
          <div className="space-y-3">
            {recentEvents.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-white/10 bg-black/30 px-4 py-10 text-center text-sm text-zinc-500">
                暂无记录
              </div>
            ) : (
              recentEvents.slice(0, 5).map((item) => (
                <div key={`${item.title}-${item.time}-${item.detail}`} className="rounded-2xl border border-white/8 bg-black/35 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium text-white">{item.title}</div>
                    <StatusBadge status={item.status} />
                  </div>
                  <div className="mt-2 text-sm leading-6 text-zinc-200">{item.detail}</div>
                  <div className="mt-2 text-xs text-zinc-500">{item.time}</div>
                </div>
              ))
            )}
          </div>
        </AdminCard>
      </div>
    </div>
  )
}

function ActionButton({
  icon,
  children,
  onClick,
}: {
  icon: ReactNode
  children: ReactNode
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-3 rounded-2xl border border-white/10 bg-black/35 px-4 py-3 text-left text-sm font-medium text-white transition-all hover:border-white/20 hover:bg-white/5"
    >
      <span className="text-zinc-400">{icon}</span>
      <span>{children}</span>
    </button>
  )
}

function formatUptime(seconds?: number | null) {
  if (seconds == null) return '--'
  const total = Math.floor(seconds)
  const hour = Math.floor(total / 3600)
  const minute = Math.floor((total % 3600) / 60)
  const second = total % 60
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')}`
}
