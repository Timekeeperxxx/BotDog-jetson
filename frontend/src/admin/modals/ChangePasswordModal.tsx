import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { usersApi } from '../../api/usersApi'
import { ToolbarButton } from '../AdminUi'
import { clearAuthState } from '../../stores/authStore'

interface Props {
  onClose: () => void
  force?: boolean
}

export function ChangePasswordModal({ onClose, force = false }: Props) {
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [])

  const handleSubmit = async () => {
    setError(null)
    if (!oldPassword || !newPassword || !confirmPassword) {
      setError('所有字段均为必填')
      return
    }
    if (newPassword.length < 8) {
      setError('新密码至少8位字符')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致')
      return
    }

    setLoading(true)
    try {
      await usersApi.changePassword({ old_password: oldPassword, new_password: newPassword })
      
      // 修改成功后登出
      clearAuthState('密码已修改，请重新登录')
      window.location.assign('/login')
    } catch (err) {
      setError(err instanceof Error ? err.message : '密码修改失败')
      setLoading(false)
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-[1000] flex items-start justify-center overflow-y-auto bg-black/70 px-4 py-6 backdrop-blur-sm sm:items-center sm:py-8">
      <div className="w-full max-w-sm rounded-3xl border border-white/10 bg-zinc-950 p-6 shadow-2xl">
        <h3 className="text-lg font-black text-white mb-2">修改密码</h3>
        <p className="text-sm text-zinc-400 mb-5">
          {force ? '您的密码已被标记为必须修改，请设置新密码' : '修改成功后将需要重新登录'}
        </p>
        
        {error && <div className="mb-4 rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{error}</div>}

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-black uppercase text-zinc-500 mb-1">当前密码</label>
            <input 
              type="password" 
              value={oldPassword} 
              onChange={e => setOldPassword(e.target.value)} 
              className="w-full rounded-xl border border-white/10 bg-black/50 px-4 py-2.5 text-sm text-white focus:border-blue-500/50 focus:outline-none"
              placeholder="输入当前密码"
            />
          </div>
          <div>
            <label className="block text-xs font-black uppercase text-zinc-500 mb-1">新密码</label>
            <input 
              type="password" 
              value={newPassword} 
              onChange={e => setNewPassword(e.target.value)} 
              className="w-full rounded-xl border border-white/10 bg-black/50 px-4 py-2.5 text-sm text-white focus:border-blue-500/50 focus:outline-none"
              placeholder="至少 8 位字符"
            />
          </div>
          <div>
            <label className="block text-xs font-black uppercase text-zinc-500 mb-1">确认新密码</label>
            <input 
              type="password" 
              value={confirmPassword} 
              onChange={e => setConfirmPassword(e.target.value)} 
              className="w-full rounded-xl border border-white/10 bg-black/50 px-4 py-2.5 text-sm text-white focus:border-blue-500/50 focus:outline-none"
              placeholder="再次输入新密码"
            />
          </div>
        </div>
        <div className="mt-8 flex justify-end gap-3">
          {!force && <ToolbarButton onClick={onClose} disabled={loading}>取消</ToolbarButton>}
          <ToolbarButton onClick={handleSubmit} disabled={loading}>{loading ? '提交中...' : '确认修改'}</ToolbarButton>
        </div>
      </div>
    </div>,
    document.body,
  )
}
