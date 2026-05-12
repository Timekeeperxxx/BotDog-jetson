import type { ReactNode } from 'react'
import type { AdminSection } from '../adminTypes'

export type AdminRole = 'viewer' | 'operator' | 'admin'

export interface AdminMenuItem {
  key: AdminSection
  label: string
  description: string
  icon: ReactNode
  visibleTo: AdminRole[]
  badge?: string
}

interface AdminSidebarProps {
  items: AdminMenuItem[]
  activeSection: AdminSection
  onSectionChange: (section: AdminSection) => void
  role: AdminRole
}

export function AdminSidebar({ items, activeSection, onSectionChange, role }: AdminSidebarProps) {
  const visibleItems = items.filter((item) => item.visibleTo.includes(role))

  return (
    <aside className="hidden w-[272px] shrink-0 border-r border-white/10 bg-[radial-gradient(circle_at_top,rgba(145,172,255,0.07),transparent_40%),linear-gradient(180deg,#0c0d11,#060708)] p-5 lg:block">
      <div className="rounded-3xl border border-white/10 bg-black/25 p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-white/10 bg-white/5">
            <span className="text-sm font-semibold text-white">BD</span>
          </div>
          <div>
            <div className="text-base font-semibold text-white">BotDog 管理后台</div>
            <div className="mt-1 text-xs text-zinc-500">系统总览 · 导航管理 · 设备与视频 · 日志中心 · 系统配置</div>
          </div>
        </div>
      </div>

      <nav className="mt-5 space-y-2">
        {visibleItems.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => onSectionChange(item.key)}
            className={`w-full rounded-2xl border px-4 py-3 text-left transition-all ${
              activeSection === item.key
                ? 'border-white/20 bg-white/10 shadow-[0_16px_40px_-24px_rgba(255,255,255,0.45)]'
                : 'border-white/8 bg-black/20 hover:border-white/14 hover:bg-white/4'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="text-zinc-300">{item.icon}</div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <div className="text-sm font-medium text-white">{item.label}</div>
                  {item.badge ? <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-zinc-400">{item.badge}</span> : null}
                </div>
              </div>
            </div>
          </button>
        ))}
      </nav>
    </aside>
  )
}
