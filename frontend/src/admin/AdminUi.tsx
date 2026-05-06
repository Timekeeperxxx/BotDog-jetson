import type { ReactNode } from 'react'
import type { ModuleHealthState } from './adminTypes'

const statusStyles: Record<ModuleHealthState, string> = {
  normal: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  degraded: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  failed: 'border-red-500/40 bg-red-500/10 text-red-300',
  waiting: 'border-sky-500/40 bg-sky-500/10 text-sky-300',
  todo: 'border-zinc-700 bg-zinc-900 text-zinc-400',
}

const statusText: Record<ModuleHealthState, string> = {
  normal: '正常',
  degraded: '降级',
  failed: '失败',
  waiting: '等待中',
  todo: 'TODO',
}

export function StatusBadge({ status }: { status: ModuleHealthState }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-black tracking-[0.18em] uppercase ${statusStyles[status]}`}>
      {statusText[status]}
    </span>
  )
}

export function AdminCard({
  title,
  subtitle,
  actions,
  children,
  className = '',
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`rounded-3xl border border-white/10 bg-[linear-gradient(180deg,rgba(18,18,20,0.96),rgba(5,5,6,0.96))] shadow-[0_24px_80px_-28px_rgba(0,0,0,0.85)] ${className}`}>
      <div className="flex items-start justify-between gap-4 border-b border-white/8 px-6 py-5">
        <div>
          <h2 className="text-sm font-black uppercase tracking-[0.24em] text-white">{title}</h2>
          {subtitle ? <p className="mt-1 text-xs text-zinc-400">{subtitle}</p> : null}
        </div>
        {actions}
      </div>
      <div className="px-6 py-5">{children}</div>
    </section>
  )
}

export function MetricTile({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/60 p-4">
      <div className="text-[10px] font-black uppercase tracking-[0.2em] text-zinc-500">{label}</div>
      <div className="mt-3 text-2xl font-black text-white">{value}</div>
      {hint ? <div className="mt-2 text-xs text-zinc-400">{hint}</div> : null}
    </div>
  )
}

export function ToolbarButton({
  children,
  onClick,
  disabled,
  danger = false,
  title,
}: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  danger?: boolean
  title?: string
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`rounded-xl border px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] transition-all ${
        danger
          ? 'border-red-500/40 text-red-300 hover:border-red-400 hover:bg-red-500/10'
          : 'border-white/12 text-white hover:border-white/30 hover:bg-white/5'
      } disabled:cursor-not-allowed disabled:border-white/8 disabled:text-white/30`}
    >
      {children}
    </button>
  )
}

export function SearchInput({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (value: string) => void
  placeholder: string
}) {
  return (
    <input
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      className="w-full rounded-xl border border-white/10 bg-black/60 px-4 py-2.5 text-sm text-white outline-none transition-all placeholder:text-zinc-600 focus:border-white/30"
    />
  )
}

export function EmptyState({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 bg-black/40 px-6 py-10 text-center">
      <div className="text-sm font-black uppercase tracking-[0.18em] text-white/80">{title}</div>
      <p className="mx-auto mt-3 max-w-xl text-sm text-zinc-400">{description}</p>
    </div>
  )
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmText,
  onCancel,
  onConfirm,
  danger = false,
  disabled = false,
}: {
  open: boolean
  title: string
  description: string
  confirmText: string
  onCancel: () => void
  onConfirm: () => void
  danger?: boolean
  disabled?: boolean
}) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-3xl border border-white/10 bg-zinc-950 p-6 shadow-[0_30px_120px_-30px_rgba(0,0,0,0.9)]">
        <div className="text-lg font-black text-white">{title}</div>
        <p className="mt-3 text-sm leading-6 text-zinc-400">{description}</p>
        <div className="mt-6 flex justify-end gap-3">
          <ToolbarButton onClick={onCancel} disabled={disabled}>取消</ToolbarButton>
          <ToolbarButton onClick={onConfirm} danger={danger} disabled={disabled}>{confirmText}</ToolbarButton>
        </div>
      </div>
    </div>
  )
}

export function TableCell({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return <td className={`border-t border-white/8 px-4 py-3 align-top text-sm text-zinc-200 ${className}`}>{children}</td>
}

export function TableHead({ children }: { children: ReactNode }) {
  return <th className="px-4 py-3 text-left text-[10px] font-black uppercase tracking-[0.2em] text-zinc-500">{children}</th>
}
