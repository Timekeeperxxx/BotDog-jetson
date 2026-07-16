import type { ReactNode } from 'react'
import { AuthStatusBar } from '../../components/AuthStatusBar'
import type { AdminSection } from '../adminTypes'
import type { AdminMenuItem, AdminRole } from './AdminSidebar'
import { AdminMobileNav } from './AdminMobileNav'

export interface AdminHeaderStatusItem {
  icon: ReactNode
  label: string
  value: string
}

interface AdminHeaderProps {
  title: string
  description: string
  statusItems?: AdminHeaderStatusItem[]
  actions?: ReactNode
  error?: string | null
  mobileItems?: AdminMenuItem[]
  role?: AdminRole
  activeSection?: AdminSection
  onSectionChange?: (section: AdminSection) => void
}

function HeaderPill({ icon, label, value }: AdminHeaderStatusItem) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-white/8 bg-[#0d1014] px-2.5 py-2 text-xs">
      <span className="text-zinc-500">{icon}</span>
      <span className="text-zinc-500">{label}</span>
      <span className="font-medium text-zinc-200">{value}</span>
    </div>
  )
}

export function AdminHeader({
  title,
  description,
  statusItems = [],
  actions,
  error,
  mobileItems = [],
  role = 'viewer',
  activeSection,
  onSectionChange,
}: AdminHeaderProps) {
  return (
    <header className="sticky top-0 z-30 border-b border-white/8 bg-[#101317]/95 px-4 py-3 lg:px-6 xl:px-7">
      <div className="flex flex-col gap-3 2xl:flex-row 2xl:items-center 2xl:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-lg font-semibold text-white">{title}</h1>
            <p className={`text-sm ${error ? 'text-red-400' : 'text-zinc-400'}`}>
              {error ? `加载异常：${error}` : description}
            </p>
          </div>
          {activeSection && onSectionChange ? (
            <AdminMobileNav
              items={mobileItems}
              activeSection={activeSection}
              onSectionChange={onSectionChange}
              role={role}
            />
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
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
