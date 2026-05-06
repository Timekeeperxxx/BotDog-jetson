import { useMemo, useState, type ReactNode } from 'react'
import { AlertOctagon, Cpu, HardDrive, Network, RefreshCw, ServerCrash } from 'lucide-react'
import type { DeviceDangerAction, DeviceOverviewData, ModuleHealthState } from '../adminTypes'
import { mapHealthStatus, mapNavStatus } from '../adminTypes'
import { AdminCard, ConfirmDialog, EmptyState, StatusBadge, TableCell, TableHead, ToolbarButton } from '../AdminUi'

const dangerActions: DeviceDangerAction[] = [
  {
    key: 'restart-backend',
    title: '重启后端',
    description: '重新拉起 FastAPI、WebSocket 和工作线程',
    supported: false,
    todo: '当前后端没有服务重启接口',
  },
  {
    key: 'restart-video',
    title: '重启视频流水线',
    description: '重新拉起 FFmpeg / MediaMTX 链路',
    supported: false,
    todo: '当前后端没有视频服务运维接口',
  },
  {
    key: 'restart-ai',
    title: '重启 AI Worker',
    description: '重新初始化模型和 RTSP 拉流',
    supported: false,
    todo: '当前后端没有 AI Worker 重启接口',
  },
  {
    key: 'reboot-device',
    title: '重启设备',
    description: '系统级重启，存在明显中断风险',
    supported: false,
    todo: '当前后端没有设备重启接口',
  },
]

export function AdminDevicePage({
  data,
  onRefresh,
}: {
  data: DeviceOverviewData
  onRefresh: () => void
}) {
  const [confirmKey, setConfirmKey] = useState<string | null>(null)

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

  return (
    <div className="space-y-6">
      <div className="grid gap-4 xl:grid-cols-4">
        <QuickFact icon={<ServerCrash size={16} />} label="项目版本" value="TODO：当前后端未暴露版本/commit 接口" />
        <QuickFact icon={<Cpu size={16} />} label="主机资源" value="TODO：缺少 CPU/内存/温度接口" />
        <QuickFact icon={<HardDrive size={16} />} label="存储资源" value="TODO：缺少磁盘使用率接口" />
        <QuickFact icon={<Network size={16} />} label="网络连通" value={`${data.networkInterfaces.length} 个已登记网口`} />
      </div>

      <AdminCard
        title="主机信息"
        subtitle="当前项目已有 /api/v1/system-info，只能读取 .env 与静态配置，不包含实时 CPU/内存。"
        actions={<ToolbarButton onClick={onRefresh}><RefreshCw size={14} className="inline-block" /> 刷新</ToolbarButton>}
      >
        <div className="grid gap-4 lg:grid-cols-2">
          {data.systemInfo.map((group) => (
            <div key={group.group} className="rounded-2xl border border-white/8 bg-black/40 p-4">
              <div className="text-sm font-black text-white">{group.group}</div>
              <div className="mt-4 space-y-3">
                {group.items.map((item) => (
                  <div key={item.key} className="rounded-xl border border-white/6 bg-black/50 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-xs font-black tracking-[0.16em] text-zinc-500">{item.label}</div>
                      <div className="text-[10px] text-zinc-600">{item.env_key}</div>
                    </div>
                    <div className="mt-2 break-all text-sm text-white">{item.value}</div>
                    <div className="mt-2 text-xs text-zinc-500">{item.note}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </AdminCard>

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <AdminCard title="网络接口" subtitle="当前可用的是“登记配置”接口，不是实时网卡探测。">
          {data.networkInterfaces.length === 0 ? (
            <EmptyState title="暂无网口配置" description="后端已提供 /api/v1/network-interfaces CRUD，但当前没有已登记项。" />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead>
                  <tr>
                    <TableHead>名称</TableHead>
                    <TableHead>网卡名</TableHead>
                    <TableHead>IP</TableHead>
                    <TableHead>用途</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>说明</TableHead>
                  </tr>
                </thead>
                <tbody>
                  {data.networkInterfaces.map((item) => (
                    <tr key={item.iface_id}>
                      <TableCell>{item.label}</TableCell>
                      <TableCell className="font-mono">{item.iface_name}</TableCell>
                      <TableCell className="font-mono">{item.ip_address || '--'}</TableCell>
                      <TableCell>{item.purpose}</TableCell>
                      <TableCell><StatusBadge status={item.enabled ? 'normal' : 'degraded'} /></TableCell>
                      <TableCell className="text-xs text-zinc-500">TODO：实时 ping / link 检测接口尚未实现</TableCell>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </AdminCard>

        <AdminCard title="服务状态" subtitle="后台优先显示可用于排障的关键模块状态。">
          <div className="space-y-3">
            {serviceRows.map((row) => (
              <div key={row.name} className="rounded-2xl border border-white/8 bg-black/40 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-black text-white">{row.name}</div>
                  <StatusBadge status={row.status} />
                </div>
                <div className="mt-2 text-sm text-zinc-300">{row.detail}</div>
              </div>
            ))}
          </div>
        </AdminCard>
      </div>

      <AdminCard title="危险操作区" subtitle="必须二次确认；当前没有后端接口的操作全部保持禁用，不伪造可执行能力。">
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-4">
          {dangerActions.map((action) => (
            <div key={action.key} className="rounded-2xl border border-red-500/20 bg-red-500/5 p-4">
              <div className="flex items-start justify-between gap-3">
                <AlertOctagon size={18} className="mt-0.5 text-red-300" />
                <StatusBadge status={action.supported ? 'waiting' : 'todo'} />
              </div>
              <div className="mt-4 text-sm font-black text-white">{action.title}</div>
              <div className="mt-2 text-sm text-zinc-300">{action.description}</div>
              <div className="mt-2 text-xs text-zinc-500">{action.todo}</div>
              <div className="mt-4">
                <ToolbarButton danger disabled={!action.supported} onClick={() => setConfirmKey(action.key)}>
                  执行
                </ToolbarButton>
              </div>
            </div>
          ))}
        </div>
      </AdminCard>

      <ConfirmDialog
        open={confirmKey !== null}
        title="确认危险操作"
        description="该区域保留二次确认流程，但当前没有对应后端接口，因此不会执行任何真实系统动作。"
        confirmText="我已知晓"
        onCancel={() => setConfirmKey(null)}
        onConfirm={() => setConfirmKey(null)}
        danger
      />
    </div>
  )
}

function QuickFact({
  icon,
  label,
  value,
}: {
  icon: ReactNode
  label: string
  value: string
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/50 p-4">
      <div className="flex items-center gap-3 text-zinc-400">
        {icon}
        <span className="text-[10px] font-black uppercase tracking-[0.18em]">{label}</span>
      </div>
      <div className="mt-4 text-sm text-white">{value}</div>
    </div>
  )
}
