import type { AdminMenuItem, AdminRole } from './AdminSidebar'
import type { AdminSection } from '../adminTypes'

interface AdminMobileNavProps {
  items: AdminMenuItem[]
  activeSection: AdminSection
  onSectionChange: (section: AdminSection) => void
  role: AdminRole
}

export function AdminMobileNav({ items, activeSection, onSectionChange, role }: AdminMobileNavProps) {
  const visibleItems = items.filter((item) => item.visibleTo.includes(role))

  if (visibleItems.length === 0) return null

  return (
    <div className="mt-2 lg:hidden">
      <select
        value={activeSection}
        onChange={(event) => onSectionChange(event.target.value as AdminSection)}
        aria-label="切换后台页面"
        className="w-full rounded-md border border-white/10 bg-[#0d1014] px-3 py-2 text-sm text-white outline-none focus:border-sky-500"
      >
        {visibleItems.map((item) => (
          <option key={item.key} value={item.key}>
            {item.label}
          </option>
        ))}
      </select>
    </div>
  )
}
