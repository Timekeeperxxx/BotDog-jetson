import { useMemo, useState, type ReactNode } from 'react'
import { AlertOctagon, HardDrive, MemoryStick, Network, ServerCrash } from 'lucide-react'
import { executeSystemAction } from '../adminApi'
import type { DeviceDangerAction, DeviceOverviewData, ModuleHealthState, SystemDangerActionKey } from '../adminTypes'
import { mapHealthStatus, mapNavStatus } from '../adminTypes'
import { AdminCard, ConfirmDialog, EmptyState, StatusBadge, TableCell, TableHead, ToolbarButton } from '../AdminUi'

const dangerActions: DeviceDangerAction[] = [
  {
    key: 'restart-backend',
    title: '重启后端',
    description: '重新拉起 FastAPI、WebSocket 和全部后台工作线程',
    effect: '后台接口和实时连接会短暂中断，通常数秒后恢复。',
    confirmation: '重启后端',
  },
  {
    key: 'restart-video',
    title: '重启视频流水线',
    description: '重新拉起 FFmpeg、MediaMTX 和摄像头拉流链路',
    effect: '所有视频画面会短暂中断，控制与导航服务不受影响。',
    confirmation: '重启视频流水线',
  },
  {
    key: 'restart-ai',
    title: '重启 AI Worker',
    description: '重新加载 AI 模型并恢复 RTSP 推理',
    effect: 'AI Worker 与后端同进程，将通过重启后端完成完整重载。',
    confirmation: '重启 AI Worker',
  },
  {
    key: 'reboot-device',
    title: '重启设备',
    description: '重启当前主机及其承载的全部 BotDog 服务',
    effect: '控制、导航、视频和后台页面都会立即离线，请确认机器狗处于安全状态。',
    confirmation: '重启设备',
  },
]

export function AdminDevicePage({
  data,
  onRefresh,
  canManageSystem,
}: {
  data: DeviceOverviewData
  onRefresh: () => void
  canManageSystem: boolean
}) {
  const [confirmKey, setConfirmKey] = useState<SystemDangerActionKey | null>(null)
  const [executingKey, setExecutingKey] = useState<SystemDangerActionKey | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const serviceRows = useMemo(() => [
    {
      name: '后端服务',
      status: mapHealthStatus(data.health?.status) as ModuleHealthState,
      detail: data.health ? `status=${data.health.status}` : '未获取到 /api/v1/system/health',
    },
    {
      name: '机器人控制',
      status: (data.health?.mavlink_connected ? 'normal' : 'degraded') as ModuleHealthState,
      detail: data.health?.mavlink_connected ? '控制链路在线' : '链路未确认或离线',
    },
    {
      name: 'ROS 导航桥',
      status: mapNavStatus(data.navState?.localization_status.status) as ModuleHealthState,
      detail: data.navState?.localization_status.message || '未获取到导航状态',
    },
    {
      name: 'AI Worker',
      status: (data.aiStatus ? 'normal' : 'waiting') as ModuleHealthState,
      detail: data.aiStatus ? `已收到 AI_STATUS，frames=${data.aiStatus.frames_processed}` : '尚未收到 AI 状态事件',
    },
    {
      name: '自动跟踪',
      status: (data.autoTrackStatus ? 'normal' : 'waiting') as ModuleHealthState,
      detail: data.autoTrackStatus ? `state=${data.autoTrackStatus.state}` : '尚未收到自动跟踪状态',
    },
  ], [data])

  const confirmedAction = dangerActions.find((action) => action.key === confirmKey) ?? null
  const resources = data.hostResources
  const diskTone = !resources
    ? 'normal'
    : resources.disk.usage_percent >= 90 ? 'critical'
      : resources.disk.usage_percent >= 80 ? 'warning' : 'normal'

  const handleDangerAction = async () => {
    if (!confirmedAction || !canManageSystem) return
    setExecutingKey(confirmedAction.key)
    setActionMessage(null)
    setActionError(null)
    try {
      const result = await executeSystemAction(confirmedAction.key, confirmedAction.confirmation)
      setActionMessage(result.message)
      if (confirmedAction.key === 'restart-video') {
        window.setTimeout(onRefresh, 1500)
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '危险操作执行失败')
    } finally {
      setExecutingKey(null)
      setConfirmKey(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <QuickFact
          icon={<ServerCrash size={16} />}
          label="主机"
          value={resources?.hostname || '暂未获取'}
          hint={resources ? `${resources.architecture} · ${resources.cpu_count} 核 · 已运行 ${formatDuration(resources.host_uptime_seconds)}` : undefined}
        />
        <QuickFact
          icon={<MemoryStick size={16} />}
          label="内存"
          value={resources ? `${resources.memory.usage_percent}%` : '暂未获取'}
          hint={resources ? `${formatBytes(resources.memory.used_bytes)} / ${formatBytes(resources.memory.total_bytes)}，可用 ${formatBytes(resources.memory.available_bytes)}` : undefined}
        />
        <QuickFact
          icon={<HardDrive size={16} />}
          label="系统磁盘"
          value={resources ? `${resources.disk.usage_percent}%` : '暂未获取'}
          hint={resources ? `${formatBytes(resources.disk.used_bytes)} / ${formatBytes(resources.disk.total_bytes)}，剩余 ${formatBytes(resources.disk.free_bytes)}` : undefined}
          tone={diskTone}
        />
        <QuickFact
          icon={<Network size={16} />}
          label="网络配置"
          value={`${data.networkInterfaces.length} 个网口`}
          hint={`${data.networkInterfaces.filter((item) => item.enabled).length} 个已启用`}
        />
      </div>

      <AdminCard title="设备信息" subtitle="机器人、图传与后端连接参数。">
        <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
          {data.systemInfo.map((group) => (
            <div key={group.group} className="rounded-md border border-white/8 bg-[#11151a] p-4">
              <div className="text-sm font-medium text-white">{group.group}</div>
              <div className="mt-4 space-y-3">
                {group.items.map((item) => (
                  <div key={item.key} className="border-t border-white/8 pt-3 first:border-0 first:pt-0">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-xs font-medium text-zinc-400">{item.label}</div>
                      <div className="text-[10px] text-zinc-400">{item.env_key}</div>
                    </div>
                    <div className="mt-1.5 break-all text-sm text-white">{item.value}</div>
                    <div className="mt-1 text-xs leading-5 text-zinc-400">{item.note}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </AdminCard>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <AdminCard title="网络接口">
          {data.networkInterfaces.length === 0 ? (
            <EmptyState title="暂无网口配置" description="后端已有网络接口配置能力，但当前没有已登记项。" />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead><tr><TableHead>名称</TableHead><TableHead>网卡名</TableHead><TableHead>IP</TableHead><TableHead>用途</TableHead><TableHead>状态</TableHead></tr></thead>
                <tbody>
                  {data.networkInterfaces.map((item) => (
                    <tr key={item.iface_id}>
                      <TableCell>{item.label}</TableCell>
                      <TableCell className="font-mono">{item.iface_name}</TableCell>
                      <TableCell className="font-mono">{item.ip_address || '--'}</TableCell>
                      <TableCell>{item.purpose}</TableCell>
                      <TableCell><StatusBadge status={item.enabled ? 'normal' : 'degraded'} /></TableCell>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </AdminCard>

        <AdminCard title="服务状态">
          <div className="divide-y divide-white/8">
            {serviceRows.map((row) => (
              <div key={row.name} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium text-white">{row.name}</div>
                  <StatusBadge status={row.status} />
                </div>
                <div className="mt-1 text-xs leading-5 text-zinc-400">{row.detail}</div>
              </div>
            ))}
          </div>
        </AdminCard>
      </div>

      <AdminCard
        title="危险操作区"
        subtitle={canManageSystem ? '仅管理员可执行；所有操作都需要二次确认并写入审计日志。' : '当前账号无执行权限，仅管理员可以操作。'}
      >
        {(actionMessage || actionError) && (
          <div className={`mb-4 rounded-md border px-4 py-3 text-sm ${
            actionError
              ? 'border-red-800/60 bg-red-950/40 text-red-300'
              : 'border-emerald-800/60 bg-emerald-950/40 text-emerald-300'
          }`}>
            {actionError || actionMessage}
          </div>
        )}
        <div className="grid gap-x-6 md:grid-cols-2">
          {dangerActions.map((action) => (
            <div key={action.key} className="flex items-start gap-3 border-b border-white/8 py-4">
              <AlertOctagon size={16} className="mt-0.5 shrink-0 text-red-300" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-white">{action.title}</div>
                <div className="mt-1 text-xs leading-5 text-zinc-400">{action.description}</div>
              </div>
              <div className="shrink-0">
                <ToolbarButton
                  danger
                  disabled={!canManageSystem || executingKey !== null}
                  onClick={() => setConfirmKey(action.key)}
                  title={canManageSystem ? `执行${action.title}` : '需要管理员权限'}
                  ariaLabel={canManageSystem ? `执行${action.title}` : `${action.title}，需要管理员权限`}
                >
                  {executingKey === action.key ? '提交中' : '执行'}
                </ToolbarButton>
              </div>
            </div>
          ))}
        </div>
      </AdminCard>

      <ConfirmDialog
        open={confirmedAction !== null}
        title={confirmedAction ? `确认${confirmedAction.title}` : '确认危险操作'}
        description={confirmedAction ? `${confirmedAction.effect} 操作提交后无法撤销，确定继续吗？` : ''}
        confirmText={executingKey ? '提交中' : '确认执行'}
        onCancel={() => setConfirmKey(null)}
        onConfirm={() => { void handleDangerAction() }}
        danger
        disabled={executingKey !== null}
      />
    </div>
  )
}

function QuickFact({
  icon,
  label,
  value,
  hint,
  tone = 'normal',
}: {
  icon: ReactNode
  label: string
  value: string
  hint?: string
  tone?: 'normal' | 'warning' | 'critical'
}) {
  const toneClass = tone === 'critical'
    ? 'border-red-700/70 bg-red-950/30'
    : tone === 'warning' ? 'border-amber-600/60 bg-amber-950/25' : 'border-white/8 bg-[#15191e]'
  const valueClass = tone === 'critical'
    ? 'text-red-300'
    : tone === 'warning' ? 'text-amber-300' : 'text-white'

  return (
    <div className={`rounded-md border px-4 py-3.5 ${toneClass}`}>
      <div className="flex items-center gap-3 text-zinc-400">{icon}<span className="text-xs font-medium">{label}</span></div>
      <div className={`mt-2 text-lg font-semibold ${valueClass}`}>{value}</div>
      {hint ? <div className="mt-1 text-xs text-zinc-400">{hint}</div> : null}
    </div>
  )
}

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / (1024 ** index)).toFixed(index >= 3 ? 1 : 0)} ${units[index]}`
}

function formatDuration(seconds: number | null) {
  if (seconds == null) return '--'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return days > 0 ? `${days} 天 ${hours} 小时` : `${hours} 小时 ${minutes} 分钟`
}
