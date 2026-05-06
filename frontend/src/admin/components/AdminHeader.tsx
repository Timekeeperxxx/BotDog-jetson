import type { ReactNode } from 'react'
import { AuthStatusBar } from '../../components/AuthStatusBar'
import type { AdminSection } from '../adminTypes'

export interface AdminHeaderStatusItem {
  icon: ReactNode
  label: string
  value: string
}

export interface AdminHeaderSectionOption {
  key: AdminSection
  label: string
}

interface AdminHeaderProps {
  title: string
  description: string
  statusItems?: AdminHeaderStatusItem[]
  actions?: ReactNode
  error?: string | null
  mobileSections?: AdminHeaderSectionOption[]
  activeSection?: AdminSection
  onSectionChange?: (section: AdminSection) => void
}

function HeaderPill({ icon, label, value }: AdminHeaderStatusItem) {
  return (
    <div className="rounded-full border border-white/10 bg-black/40 px-3 py-2">
      <div className="flex items-center gap-2 text-zinc-400">
        {icon}
        <span className="text-[10px] font-black uppercase tracking-[0.18em]">{label}</span>
      </div>
      <div className="mt-1 text-xs text-white">{value}</div>
    </div>
  )
}

export function AdminHeader({
  title,
  description,
  statusItems = [],
  actions,
  error,
  mobileSections = [],
  activeSection,
  onSectionChange,
}: AdminHeaderProps) {
  return (
    <header className="sticky top-0 z-30 border-b border-white/10 bg-[linear-gradient(180deg,rgba(7,8,10,0.95),rgba(7,8,10,0.82))] px-4 py-4 backdrop-blur xl:px-8">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="text-[11px] font-black uppercase tracking-[0.28em] text-zinc-500">机器狗后台管理界面</div>
          <div className="mt-2 text-2xl font-black text-white">{title}</div>
          <div className="mt-1 text-sm text-zinc-400">{error ? `加载异常：${error}` : description}</div>
          {mobileSections.length > 0 && activeSection && onSectionChange ? (
            <div className="mt-3 xl:hidden">
              <select
                value={activeSection}
                onChange={(event) => onSectionChange(event.target.value as AdminSection)}
                className="w-full rounded-2xl border border-white/10 bg-black/60 px-4 py-3 text-sm text-white outline-none focus:border-white/30"
              >
                {mobileSections.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {statusItems.map((item) => (
            <HeaderPill key={`${item.label}-${item.value}`} {...item} />
          ))}
          {actions}
          <AuthStatusBar variant="bar" />
        </div>
      </div>
    </header>
  )
}
