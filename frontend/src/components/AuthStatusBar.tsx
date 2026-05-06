/**
 * AuthStatusBar — 登录状态栏
 *
 * 显示当前用户名、角色，以及退出登录按钮。
 * 退出前尝试发送 stop 命令（失败不阻塞），然后清除 authStore。
 *
 * Props:
 *   onLogout — 可选，调用方控制退出后的跳转行为。
 *              未提供时默认跳到 /login。
 *   variant  — 'bar'（横向嵌入型，适合 header）
 *              'overlay'（fixed 右上角悬浮，适合全屏页面）
 */

import { useState } from 'react'
import { LogOut, User } from 'lucide-react'
import { clearAuthState, useAuthState } from '../stores/authStore'
import { getApiUrl } from '../config/api'
import { ChangePasswordModal } from '../admin/modals/ChangePasswordModal'

const ROLE_LABEL: Record<string, string> = {
  admin: 'Admin',
  operator: 'Operator',
  viewer: 'Viewer',
}

interface Props {
  onLogout?: () => void
  variant?: 'bar' | 'overlay'
}

async function tryStopRobot(): Promise<void> {
  try {
    await fetch(getApiUrl('/api/v1/control/stop'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ x: 0, y: 0, z: 0, r: 0 }),
    })
  } catch {
    // 退出不依赖 stop 成功，Watchdog 作为兜底
  }
}

export function AuthStatusBar({ onLogout, variant = 'bar' }: Props) {
  const auth = useAuthState()
  const [loggingOut, setLoggingOut] = useState(false)
  const [changePasswordOpen, setChangePasswordOpen] = useState(false)

  if (!auth.accessToken && !auth.authBypass) return null

  const handleLogout = async () => {
    setLoggingOut(true)
    // 退出前发 stop，失败不阻塞
    await tryStopRobot()
    clearAuthState('已主动退出登录')
    if (onLogout) {
      onLogout()
    } else {
      window.location.assign('/login')
    }
  }

  const username = auth.username || '—'
  const role = auth.role ? (ROLE_LABEL[auth.role] ?? auth.role) : '—'

  if (variant === 'overlay') {
    return (
      <div
        className="fixed left-1/2 top-4 z-40 flex -translate-x-1/2 items-center gap-2 rounded-lg border border-white/10 bg-black/75 px-3 py-2 text-xs text-white shadow-lg backdrop-blur-sm"
        style={{ maxWidth: 'calc(100vw - 2rem)' }}
      >
        <User size={12} className="shrink-0 text-zinc-400" />
        <span className="truncate font-mono text-zinc-200">{username}</span>
        <span className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider text-zinc-400">
          {role}
        </span>
        <button
          onClick={() => setChangePasswordOpen(true)}
          title="修改密码"
          className="ml-1 flex items-center gap-1 rounded border border-white/10 bg-white/5 px-2 py-1 text-[10px] font-black uppercase tracking-wider text-zinc-300 transition-all hover:border-white/20 hover:bg-white/10 hover:text-white"
        >
          修改密码
        </button>
        <button
          onClick={() => void handleLogout()}
          disabled={loggingOut}
          title="退出登录"
          className="ml-1 flex items-center gap-1 rounded border border-white/10 bg-white/5 px-2 py-1 text-[10px] font-black uppercase tracking-wider text-zinc-300 transition-all hover:border-red-500/40 hover:bg-red-500/10 hover:text-red-300 disabled:opacity-50"
        >
          <LogOut size={10} />
          {loggingOut ? '退出中' : '退出'}
        </button>
        {changePasswordOpen && <ChangePasswordModal onClose={() => setChangePasswordOpen(false)} />}
      </div>
    )
  }

  // variant === 'bar' — 嵌入 header
  return (
    <div className="flex items-center gap-2">
      <User size={13} className="text-zinc-400" />
      <span className="text-xs font-mono text-zinc-300">{username}</span>
      <span className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider text-zinc-500">
        {role}
      </span>
      <button
        onClick={() => setChangePasswordOpen(true)}
        title="修改密码"
        className="flex items-center gap-1.5 rounded-xl border border-white/10 px-3 py-2 text-[11px] font-black uppercase tracking-[0.15em] text-zinc-400 transition-all hover:border-white/20 hover:bg-white/10 hover:text-white"
      >
        修改密码
      </button>
      <button
        onClick={() => void handleLogout()}
        disabled={loggingOut}
        title="退出登录"
        className="flex items-center gap-1.5 rounded-xl border border-white/10 px-3 py-2 text-[11px] font-black uppercase tracking-[0.15em] text-zinc-400 transition-all hover:border-red-500/40 hover:bg-red-500/10 hover:text-red-300 disabled:opacity-50"
      >
        <LogOut size={12} />
        {loggingOut ? '退出中' : '退出登录'}
      </button>
      {changePasswordOpen && <ChangePasswordModal onClose={() => setChangePasswordOpen(false)} />}
    </div>
  )
}
