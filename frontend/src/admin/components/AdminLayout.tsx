import type { ReactNode } from 'react'

interface AdminLayoutProps {
  sidebar: ReactNode
  header: ReactNode
  children: ReactNode
}

export function AdminLayout({ sidebar, header, children }: AdminLayoutProps) {
  return (
    <div className="flex min-h-screen bg-[#060708] text-white">
      {sidebar}
      <main className="min-w-0 flex-1">
        {header}
        <div className="px-4 py-6 xl:px-8">{children}</div>
      </main>
    </div>
  )
}
