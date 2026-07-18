import { useId, type ReactNode } from 'react'
import type { ModuleHealthState } from './adminTypes'
import { useModalFocus } from '../hooks/useModalFocus'

const statusStyles: Record<ModuleHealthState, string> = {
  normal: 'border-emerald-700/60 bg-emerald-950/50 text-emerald-300',
  degraded: 'border-amber-700/60 bg-amber-950/50 text-amber-300',
  failed: 'border-red-700/60 bg-red-950/50 text-red-300',
  waiting: 'border-sky-700/60 bg-sky-950/50 text-sky-300',
  todo: 'border-zinc-700 bg-zinc-900 text-zinc-400',
}

const statusText: Record<ModuleHealthState, string> = {
  normal: '正常',
  degraded: '降级',
  failed: '失败',
  waiting: '等待中',
  todo: '未接入',
}

export function StatusBadge({ status }: { status: ModuleHealthState }) {
  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${statusStyles[status]}`}>
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
    <section className={`rounded-lg border border-white/8 bg-[#15191e] ${className}`}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/8 px-5 py-3.5">
        <div>
          <h2 className="text-sm font-semibold text-white">{title}</h2>
          {subtitle ? <p className="mt-1 text-xs leading-5 text-zinc-400">{subtitle}</p> : null}
        </div>
        {actions}
      </div>
      <div className="px-5 py-4">{children}</div>
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
    <div className="rounded-md border border-white/8 bg-[#15191e] p-4">
      <div className="text-xs font-medium text-zinc-400">{label}</div>
      <div className="mt-1.5 text-xl font-semibold text-white">{value}</div>
      {hint ? <div className="mt-1.5 text-xs text-zinc-400">{hint}</div> : null}
    </div>
  )
}

export function ToolbarButton({
  children,
  onClick,
  disabled,
  danger = false,
  title,
  ariaLabel,
}: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  danger?: boolean
  title?: string
  ariaLabel?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={ariaLabel}
      className={`rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
        danger
          ? 'border-red-800/70 text-red-300 hover:border-red-600 hover:bg-red-950/50'
          : 'border-white/12 bg-[#1b2026] text-zinc-100 hover:border-white/25 hover:bg-[#222831]'
      } disabled:cursor-not-allowed disabled:border-white/8 disabled:bg-transparent disabled:text-white/30`}
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
      className="w-full rounded-md border border-white/10 bg-[#0d1014] px-3 py-2 text-sm text-white outline-none transition-colors placeholder:text-zinc-600 focus:border-sky-600"
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
    <div className="rounded-md border border-dashed border-white/10 px-6 py-8 text-center">
      <div className="text-sm font-medium text-white/80">{title}</div>
      <p className="mx-auto mt-2 max-w-xl text-sm text-zinc-400">{description}</p>
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
  const titleId = useId()
  const descriptionId = useId()
  const dialogRef = useModalFocus<HTMLDivElement>({
    open,
    onClose: onCancel,
    closeOnEscape: !disabled,
  })

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/75 px-4">
      <div
        ref={dialogRef}
        className="w-full max-w-md rounded-lg border border-white/12 bg-[#15191e] p-5 shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
      >
        <div id={titleId} className="text-lg font-semibold text-white">{title}</div>
        <p id={descriptionId} className="mt-3 text-sm leading-6 text-zinc-300">{description}</p>
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
  return <th className="bg-[#11151a] px-4 py-2.5 text-left text-xs font-medium text-zinc-400">{children}</th>
}
