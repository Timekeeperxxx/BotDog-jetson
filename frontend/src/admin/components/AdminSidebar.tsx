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
    <aside className="hidden w-[288px] shrink-0 border-r border-white/10 bg-[radial-gradient(circle_at_top,rgba(145,172,255,0.08),transparent_40%),linear-gradient(180deg,#0c0d11,#060708)] p-6 lg:block">
      <div className="rounded-3xl border border-white/10 bg-black/30 p-5">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-white/10 bg-white/5">
            <span className="text-sm font-black uppercase tracking-[0.2em] text-white">BD</span>
          </div>
          <div>
            <div className="text-sm font-black uppercase tracking-[0.22em] text-white">BotDog Admin</div>
            <div className="mt-1 text-xs text-zinc-500">后台管理 / 运维 / 权限</div>
          </div>
        </div>
      </div>

      <nav className="mt-6 space-y-2">
        {visibleItems.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => onSectionChange(item.key)}
            className={`w-full rounded-2xl border p-4 text-left transition-all ${
              activeSection === item.key
                ? 'border-white/20 bg-white/10 shadow-[0_16px_40px_-24px_rgba(255,255,255,0.45)]'
                : 'border-white/8 bg-black/20 hover:border-white/14 hover:bg-white/4'
            }`}
          >
            <div className="flex items-start gap-3">
              <div className="mt-0.5 text-zinc-300">{item.icon}</div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <div className="text-sm font-black text-white">{item.label}</div>
                  {item.badge ? (
                    <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[9px] font-black uppercase tracking-[0.18em] text-zinc-400">
                      {item.badge}
                    </span>
                  ) : null}
                </div>
                <div className="mt-1 text-xs text-zinc-500">{item.description}</div>
              </div>
            </div>
          </button>
        ))}
      </nav>

      <div className="mt-6 rounded-2xl border border-dashed border-white/10 bg-black/30 p-4 text-xs leading-6 text-zinc-500">
        当前后台只接入本地项目里真实存在的接口。缺失能力会明确标记 TODO，不伪造“看起来能用”的运维功能。
      </div>
    </aside>
  )
}
