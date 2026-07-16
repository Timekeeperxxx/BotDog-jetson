import type { ReactNode } from 'react'

interface AdminLayoutProps {
  sidebar: ReactNode
  header: ReactNode
  children: ReactNode
}

export function AdminLayout({ sidebar, header, children }: AdminLayoutProps) {
  return (
    <div className="admin-shell flex min-h-screen bg-[#0d1014] text-white">
      {sidebar}
      <main className="min-w-0 flex-1 bg-[#101317]">
        {header}
        <div className="px-4 py-5 lg:px-6 xl:px-7">{children}</div>
      </main>
    </div>
  )
}
