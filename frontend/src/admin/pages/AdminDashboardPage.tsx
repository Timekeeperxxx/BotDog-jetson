import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Activity, Bot, Camera, Cpu, MapPinned, Server, ShieldCheck } from 'lucide-react'
import type { AdminDashboardData, AdminServiceCard } from '../adminTypes'
import { mapHealthStatus, mapNavStatus } from '../adminTypes'
import { AdminCard, MetricTile, StatusBadge } from '../AdminUi'
import { apiFetch } from '../../api/apiFetch'
import type { AuthStatusResult } from '../../api/auth'
import { useAuthState } from '../../stores/authStore'

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

function formatUptime(seconds?: number | null) {
  if (seconds == null) return '--'
  const total = Math.floor(seconds)
  const hour = Math.floor(total / 3600)
  const minute = Math.floor((total % 3600) / 60)
  const second = total % 60
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')}`
}

export function AdminDashboardPage({ data }: { data: AdminDashboardData }) {
  const auth = useAuthState()
  const [authStatus, setAuthStatus] = useState<AuthStatusResult | null>(null)
  const [authStatusError, setAuthStatusError] = useState<string | null>(null)
  const [safetyStatus, setSafetyStatus] = useState<Record<string, unknown> | null>(null)
  const [safetyError, setSafetyError] = useState<string | null>(null)

  useEffect(() => {
    apiFetch<AuthStatusResult>('/api/v1/auth/status')
      .then(setAuthStatus)
      .catch((err: unknown) => setAuthStatusError(err instanceof Error ? err.message : '暂不可用'))
  }, [])

  useEffect(() => {
    apiFetch<Record<string, unknown>>('/api/v1/system/safety')
      .then(setSafetyStatus)
      .catch((err: unknown) => setSafetyError(err instanceof Error ? err.message : '暂不可用'))
  }, [])

  const serviceCards = useMemo<AdminServiceCard[]>(() => {
    const activeSources = data.videoSources.filter((item) => item.enabled)
    return [
      {
        key: 'backend',
        title: '后端服务',
        status: mapHealthStatus(data.health?.status),
        detail: data.health ? `健康状态=${data.health.status}` : '未获取到 /api/v1/system/health',
        extra: data.health ? `运行时长=${formatUptime(data.health.uptime)}` : 'TODO: 增加启动摘要接口',
      },
      {
        key: 'robot',
        title: '机器人控制',
        status: data.health?.mavlink_connected ? 'normal' : 'degraded',
        detail: data.health?.mavlink_connected ? '控制链路在线' : '链路未确认或未连接',
        extra: '来源=/api/v1/system/health',
      },
      {
        key: 'telemetry',
        title: '遥测服务',
        status: data.health?.mavlink_connected ? 'normal' : 'waiting',
        detail: data.health?.mavlink_connected ? 'MAVLink / DDS 数据可用' : '等待遥测源恢复',
        extra: 'TODO: 增加队列积压/广播频率接口',
      },
      {
        key: 'video',
        title: '视频流水线',
        status: activeSources.length > 0 ? 'normal' : 'degraded',
        detail: activeSources.length > 0 ? `已启用 ${activeSources.length} 路视频源` : '未检测到启用的视频源',
        extra: 'MediaMTX / WHEP 暂无独立状态接口',
      },
      {
        key: 'ai',
        title: 'AI Worker',
        status: data.aiStatus ? 'normal' : 'waiting',
        detail: data.aiStatus ? `frames=${data.aiStatus.frames_processed} detections=${data.aiStatus.detections_count}` : '未收到 AI_STATUS 事件',
        extra: data.autoTrackStatus ? `自动跟踪=${data.autoTrackStatus.state}` : 'TODO: 增加 AI 健康探针',
      },
      {
        key: 'ros',
        title: 'ROS 导航',
        status: mapNavStatus(data.navState?.localization_status.status),
        detail: data.navState
          ? `定位=${data.navState.localization_status.status}，导航=${data.navState.navigation_status.status}`
          : '未获取到导航状态',
        extra: data.navState?.robot_pose
          ? `机器人位姿=(${data.navState.robot_pose.x.toFixed(2)}, ${data.navState.robot_pose.y.toFixed(2)})`
          : '等待 nav.state / nav.websocket',
      },
    ]
  }, [data])

  const latestLog = data.logs[0]
  const latestEvidence = data.evidence[0]
  const latestAlerts = data.alerts.slice(0, 5)

  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-4">
        <MetricTile label="后端运行时长" value={formatUptime(data.health?.uptime)} hint="来源 /api/v1/system/health" />
        <MetricTile label="AI 已处理帧数" value={String(data.aiStatus?.frames_processed ?? '--')} hint="来源 WebSocket 事件流" />
        <MetricTile label="当前检测数" value={String(data.aiStatus?.detections_count ?? '--')} hint={data.aiStatus ? `模式=${data.aiStatus.mode}` : '等待 AI_STATUS'} />
        <MetricTile label="导航目标" value={data.navState?.navigation_status.target_name || '空闲'} hint={data.navState?.navigation_status.message || '暂无导航任务'} />
      </div>

      {/* ─── 安全总览 ─── */}
      <AdminCard
        title="安全总览"
        subtitle="登录状态、鉴权开关、SafetySupervisor、当前导航目标。数据失败时显示暂不可用。"
      >
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {/* 当前用户 */}
          <SecurityTile
            icon={<ShieldCheck size={14} />}
            title="当前用户"
            rows={[
              { label: '用户名', value: auth.username || '--' },
              { label: '角色', value: auth.role || '--' },
              { label: '须改密', value: auth.must_change_password ? '是' : '否' },
              { label: '登录方式', value: auth.authBypass ? '开发绕过' : 'JWT' },
            ]}
          />
          {/* 鉴权状态 */}
          <SecurityTile
            icon={<ShieldCheck size={14} />}
            title="鉴权状态"
            error={authStatusError}
            rows={authStatus ? [
              { label: 'AUTH_ENABLED', value: authStatus.auth_enabled ? '已开启 ✓' : '已关闭 ⚠' },
              { label: '后端用户', value: authStatus.current_user.username },
              { label: '后端角色', value: authStatus.current_user.role },
              { label: '须改密', value: authStatus.current_user.must_change_password ? '是' : '否' },
            ] : []}
          />
          {/* SafetySupervisor */}
          <SecurityTile
            icon={<ShieldCheck size={14} />}
            title="运动安全"
            error={safetyError}
            rows={safetyStatus ? [
              { label: '允许运动', value: safetyStatus.safe_to_move ? '是 ✓' : '否 ✗' },
              { label: '系统状态', value: String(safetyStatus.system_state ?? '--') },
              { label: '适配器就绪', value: safetyStatus.control_adapter_ready ? '是' : '否' },
              { label: '阻止原因', value: Array.isArray(safetyStatus.reasons) && safetyStatus.reasons.length > 0 ? (safetyStatus.reasons as string[]).join('；') : '无' },
            ] : []}
          />
        </div>
      </AdminCard>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_0.9fr]">
        <AdminCard
          title="系统服务状态"
          subtitle="优先复用现有健康检查、导航状态、视频源和事件流；缺失项明确标为 TODO。"
        >
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {serviceCards.map((card) => (
              <div key={card.key} className="rounded-2xl border border-white/8 bg-black/40 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-black text-white">{card.title}</div>
                  <StatusBadge status={card.status} />
                </div>
                <div className="mt-4 text-sm text-zinc-200">{card.detail}</div>
                <div className="mt-3 text-xs text-zinc-500">{card.extra}</div>
              </div>
            ))}
          </div>
        </AdminCard>

        <AdminCard title="主链路摘要" subtitle="现场排障优先显示关键链路。">
          <div className="space-y-4">
            <SummaryRow icon={<Server size={16} />} label="API 服务" value={data.health ? `状态=${data.health.status}` : '未获取到状态'} />
            <SummaryRow icon={<Bot size={16} />} label="机器人控制" value={data.health?.mavlink_connected ? '在线' : '离线或等待中'} />
            <SummaryRow icon={<Camera size={16} />} label="视频源" value={`${data.videoSources.filter((item) => item.enabled).length}/${data.videoSources.length} 启用`} />
            <SummaryRow icon={<Activity size={16} />} label="自动跟踪" value={data.autoTrackStatus?.state || '等待中'} />
            <SummaryRow icon={<MapPinned size={16} />} label="ROS 导航" value={data.navState?.localization_status.message || '未获取到定位状态'} />
            <SummaryRow icon={<Cpu size={16} />} label="主机资源" value="TODO：当前后端无 CPU/内存/磁盘/温度接口" />
          </div>
        </AdminCard>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_1fr_1fr]">
        <AdminCard title="最新告警" subtitle="来自 /ws/event。">
          <div className="space-y-3">
            {latestAlerts.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-white/10 bg-black/40 px-4 py-8 text-sm text-zinc-500">
                当前没有新的告警事件。
              </div>
            ) : latestAlerts.map((alert, index) => (
              <div key={`${alert.timestamp}-${index}`} className="rounded-2xl border border-white/8 bg-black/40 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-black text-white">{alert.message || alert.event_type}</div>
                  <StatusBadge status={alert.severity === 'CRITICAL' ? 'failed' : 'degraded'} />
                </div>
                <div className="mt-2 text-xs text-zinc-400">
                  {alert.event_code || alert.event_type} · {formatRelativeTime(alert.timestamp)}
                </div>
              </div>
            ))}
          </div>
        </AdminCard>

        <AdminCard title="最新日志" subtitle="来源 /api/v1/logs。">
          <div className="space-y-3">
            {data.logs.slice(0, 5).map((log) => (
              <div key={log.log_id} className="rounded-2xl border border-white/8 bg-black/40 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-black text-white">{log.module}</div>
                  <div className="text-[10px] font-black uppercase tracking-[0.18em] text-zinc-500">{log.level}</div>
                </div>
                <div className="mt-3 text-sm text-zinc-300">{log.message}</div>
                <div className="mt-2 text-xs text-zinc-500">{formatRelativeTime(log.created_at)}</div>
              </div>
            ))}
            {!latestLog ? <div className="text-sm text-zinc-500">暂无日志。</div> : null}
          </div>
        </AdminCard>

        <AdminCard title="告警证据" subtitle="优先显示最近触发的证据记录。">
          <div className="space-y-3">
            {latestEvidence ? (
              <div className="rounded-2xl border border-white/8 bg-black/40 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-black text-white">{latestEvidence.message || latestEvidence.event_type}</div>
                  <StatusBadge status={latestEvidence.severity === 'CRITICAL' ? 'failed' : 'degraded'} />
                </div>
                <div className="mt-3 text-sm text-zinc-300">文件：{latestEvidence.file_path || '无截图文件'}</div>
                <div className="mt-2 text-xs text-zinc-500">{formatRelativeTime(latestEvidence.created_at)}</div>
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-white/10 bg-black/40 px-4 py-8 text-sm text-zinc-500">
                暂无证据记录。
              </div>
            )}
            <div className="rounded-2xl border border-dashed border-amber-500/20 bg-amber-500/5 p-4 text-sm text-amber-200">
              TODO：当前后端没有主机 CPU、内存、磁盘、温度、网络延迟聚合接口，本页先明确标记为空缺项，不伪造真实运维指标。
            </div>
          </div>
        </AdminCard>
      </div>
    </div>
  )
}

function SummaryRow({
  icon,
  label,
  value,
}: {
  icon: ReactNode
  label: string
  value: string
}) {
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-white/8 bg-black/40 px-4 py-3">
      <div className="mt-0.5 text-zinc-400">{icon}</div>
      <div>
        <div className="text-[10px] font-black uppercase tracking-[0.18em] text-zinc-500">{label}</div>
        <div className="mt-1 text-sm text-zinc-200">{value}</div>
      </div>
    </div>
  )
}

function SecurityTile({
  icon,
  title,
  rows,
  error,
}: {
  icon: ReactNode
  title: string
  rows: { label: string; value: string }[]
  error?: string | null
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/60 p-4 space-y-2">
      <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-zinc-400">
        <span className="text-zinc-500">{icon}</span>
        {title}
      </div>
      {error ? (
        <div className="text-xs text-amber-400/80 bg-amber-500/5 border border-amber-500/20 rounded px-2 py-1">
          暂不可用：{error}
        </div>
      ) : rows.length === 0 ? (
        <div className="text-xs text-zinc-500">加载中...</div>
      ) : (
        rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-2">
            <span className="text-[10px] text-zinc-500 shrink-0">{row.label}</span>
            <span className="text-xs text-zinc-200 text-right break-all">{row.value}</span>
          </div>
        ))
      )}
    </div>
  )
}
