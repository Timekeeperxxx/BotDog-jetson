import type { ReactNode } from 'react'
import { ExternalLink, FlaskConical, Radar, ServerCog } from 'lucide-react'
import { AdminCard, EmptyState, ToolbarButton } from '../AdminUi'

export function AdminDiagnosticsPage({
  onOpenPatrol,
}: {
  onOpenPatrol: () => void
}) {
  return (
    <div className="space-y-6">
      <AdminCard title="诊断工具" subtitle="这里只放可验证的排查入口，不伪造未实现的诊断面板。">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <DiagTile icon={<ServerCog size={14} />} title="/api/v1/system/safety" desc="检查当前是否允许运动，以及阻止原因。" />
          <DiagTile icon={<Radar size={14} />} title="/api/v1/nav/current-goal" desc="检查运行时 current_goal.json 是否已写入。" />
          <DiagTile icon={<FlaskConical size={14} />} title="/api/v1/auth/status" desc="检查当前登录态和角色信息。" />
        </div>
      </AdminCard>

      <AdminCard title="快捷入口" subtitle="用于现场排障，不替代正式后台流程。">
        <div className="flex flex-wrap gap-3">
          <ToolbarButton onClick={onOpenPatrol}><ExternalLink size={14} className="inline-block" /> 打开导航页</ToolbarButton>
          <a
            href="/api/v1/system/safety"
            target="_blank"
            rel="noreferrer"
            className="rounded-xl border border-white/12 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-white transition-all hover:border-white/30 hover:bg-white/5"
          >
            查看安全接口
          </a>
          <a
            href="/api/v1/nav/current-goal"
            target="_blank"
            rel="noreferrer"
            className="rounded-xl border border-white/12 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-white transition-all hover:border-white/30 hover:bg-white/5"
          >
            查看当前目标
          </a>
        </div>
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
}: {
  icon: ReactNode
  title: string
  desc: string
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/50 p-4">
      <div className="flex items-center gap-2 text-white">
        {icon}
        <span className="text-sm font-black">{title}</span>
      </div>
      <div className="mt-3 text-sm text-zinc-400">{desc}</div>
    </div>
  )
}
