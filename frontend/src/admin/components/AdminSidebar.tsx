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
    <aside className="sticky top-0 hidden h-screen w-56 shrink-0 overflow-y-auto border-r border-white/8 bg-[#0b0e12] p-3 lg:block">
      <div className="border-b border-white/8 px-2 pb-4 pt-2">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-sky-700 text-xs font-semibold text-white">
            BD
          </div>
          <div>
            <div className="text-sm font-semibold text-white">BotDog 后台</div>
            <div className="mt-0.5 text-xs text-zinc-400">系统管理</div>
          </div>
        </div>
      </div>

      <nav className="mt-3 space-y-1" aria-label="后台主导航">
        {visibleItems.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => onSectionChange(item.key)}
            title={item.description}
            aria-current={activeSection === item.key ? 'page' : undefined}
            className={`w-full rounded-md border-l-2 px-3 py-2.5 text-left transition-colors ${
              activeSection === item.key
                ? 'border-sky-500 bg-white/8 text-white'
                : 'border-transparent text-zinc-400 hover:bg-white/5 hover:text-zinc-100'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className={activeSection === item.key ? 'text-sky-400' : 'text-zinc-500'}>{item.icon}</div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <div className="text-sm font-medium">{item.label}</div>
                  {item.badge ? <span className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] text-zinc-300">{item.badge}</span> : null}
                </div>
              </div>
            </div>
          </button>
        ))}
      </nav>
    </aside>
  )
}
