import type { ReactNode } from 'react'
import { Activity, Bot, ShieldCheck } from 'lucide-react'
import type { HealthResponse, AdminLogEntry } from '../adminTypes'
import type { AIStatus, AutoTrackStatus } from '../../types/event'
import type { NavStateResponse } from '../../types/navState'
import type { VideoSource } from '../../types/admin'
import { AdminCard, MetricTile, StatusBadge, ToolbarButton } from '../AdminUi'

interface AdminAiGuardPageProps {
  health: HealthResponse | null
  aiStatus: AIStatus | null
  autoTrackStatus: AutoTrackStatus | null
  navState: NavStateResponse | null
  logs: AdminLogEntry[]
  videoSources: VideoSource[]
  onOpenOperator: () => void
}

export function AdminAiGuardPage({
  health,
  aiStatus,
  autoTrackStatus,
  navState,
  logs,
  videoSources,
  onOpenOperator,
}: AdminAiGuardPageProps) {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-4">
        <MetricTile label="AI 状态" value={aiStatus ? aiStatus.mode : '等待中'} hint="来自 /ws/event" />
        <MetricTile label="自动跟踪" value={autoTrackStatus?.state || '等待中'} hint={autoTrackStatus?.enabled ? '已启用' : '未启用'} />
        <MetricTile label="视频源" value={String(videoSources.filter((item) => item.enabled).length)} hint="启用中的视频源" />
        <MetricTile label="机器人控制" value={health?.mavlink_connected ? '在线' : '离线'} hint={navState?.navigation_status.message || '导航状态待接入'} />
      </div>

      <AdminCard
        title="AI 与驱离总览"
        subtitle="该模块承接运行态摘要和操作入口，不在后台重做视觉算法或驱离链路。"
        actions={<ToolbarButton onClick={onOpenOperator}>进入操作台</ToolbarButton>}
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <SummaryTile icon={<Bot size={14} />} title="AI Worker" value={aiStatus ? `frames=${aiStatus.frames_processed}` : '未连接'} />
          <SummaryTile icon={<Activity size={14} />} title="自动跟踪" value={autoTrackStatus ? autoTrackStatus.state : '未连接'} />
          <SummaryTile icon={<ShieldCheck size={14} />} title="驱离状态" value={autoTrackStatus?.enabled ? '可能影响机器人移动' : '未启用'} />
        </div>
      </AdminCard>

      <AdminCard title="已知限制" subtitle="当前后台只展示状态和入口，复杂操作仍在操作台中完成。">
        <div className="space-y-3 text-sm text-zinc-300">
          <div className="rounded-2xl border border-white/8 bg-black/40 p-4">视觉识别参数和视频源配置已归入“设备与视频”模块。</div>
          <div className="rounded-2xl border border-white/8 bg-black/40 p-4">自动跟踪和驱离执行细节仍以操作台为准，这里不重做控制按钮。</div>
          <div className="rounded-2xl border border-white/8 bg-black/40 p-4">如果后续要做更细的 AI 运维，再拆子页和专门的诊断接口。</div>
        </div>
      </AdminCard>

      <AdminCard title="最近相关日志" subtitle="只做可读摘要，不伪造训练或推理细节。">
        {logs.slice(0, 4).length === 0 ? (
          <div className="text-sm text-zinc-500">暂无相关日志。</div>
        ) : (
          <div className="space-y-3">
            {logs.slice(0, 4).map((log) => (
              <div key={log.log_id} className="rounded-2xl border border-white/8 bg-black/40 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-black text-white">{log.module}</div>
                  <StatusBadge status={log.level === 'ERROR' || log.level === 'CRITICAL' ? 'failed' : 'waiting'} />
                </div>
                <div className="mt-2 text-sm text-zinc-300">{log.message}</div>
              </div>
            ))}
          </div>
        )}
      </AdminCard>
    </div>
  )
}

function SummaryTile({ icon, title, value }: { icon: ReactNode; title: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/50 p-4">
      <div className="flex items-center gap-2 text-zinc-400">
        {icon}
        <span className="text-[10px] font-black uppercase tracking-[0.18em]">{title}</span>
      </div>
      <div className="mt-3 text-sm text-white">{value}</div>
    </div>
  )
}
