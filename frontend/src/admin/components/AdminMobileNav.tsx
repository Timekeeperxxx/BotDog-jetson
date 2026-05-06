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
    <div className="mt-3 lg:hidden">
      <select
        value={activeSection}
        onChange={(event) => onSectionChange(event.target.value as AdminSection)}
        className="w-full rounded-2xl border border-white/10 bg-black/60 px-4 py-3 text-sm text-white outline-none focus:border-white/30"
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
