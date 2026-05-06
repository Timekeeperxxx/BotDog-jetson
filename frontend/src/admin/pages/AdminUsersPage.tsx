import { useEffect, useState } from 'react'
import { usersApi, type User, type Role } from '../../api/usersApi'
import { ConfirmDialog, ToolbarButton } from '../AdminUi'
import { useAuthState } from '../../stores/authStore'

export function AdminUsersPage() {
  const auth = useAuthState()
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(false)
  const [pageError, setPageError] = useState<string | null>(null)

  const [formOpen, setFormOpen] = useState(false)
  const [editUser, setEditUser] = useState<User | null>(null)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  
  // Create / Edit Form
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [role, setRole] = useState<Role>('viewer')
  const [enabled, setEnabled] = useState(true)
  const [mustChangePassword, setMustChangePassword] = useState(false)
  
  // Reset Password Form
  const [resetModalOpen, setResetModalOpen] = useState(false)
  const [resetUser, setResetUser] = useState<User | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [resetConfirmPassword, setResetConfirmPassword] = useState('')
  const [resetError, setResetError] = useState<string | null>(null)

  const [confirmAction, setConfirmAction] = useState<{
    type: 'delete' | 'disable' | 'changeRole' | 'resetPassword'
    user: User
    targetRole?: Role
  } | null>(null)

  const fetchUsers = async () => {
    setLoading(true)
    setPageError(null)
    try {
      const data = await usersApi.listUsers()
      setUsers(data)
    } catch (err) {
      setPageError(err instanceof Error ? err.message : '获取用户列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (auth.role === 'admin') {
      void fetchUsers()
    }
  }, [auth.role])

  if (auth.role !== 'admin') {
    return (
      <div className="flex h-[400px] items-center justify-center text-zinc-500">
        无权限访问用户与权限管理。需要 admin 角色。
      </div>
    )
  }

  const openCreate = () => {
    setEditUser(null)
    setUsername('')
    setPassword('')
    setConfirmPassword('')
    setRole('viewer')
    setEnabled(true)
    setMustChangePassword(true)
    setFormError(null)
    setFormOpen(true)
  }

  const openEdit = (u: User) => {
    setEditUser(u)
    setUsername(u.username)
    setRole(u.role)
    setEnabled(u.enabled)
    setMustChangePassword(u.must_change_password)
    setFormError(null)
    setFormOpen(true)
  }

  const closeForm = () => {
    setFormOpen(false)
    setPassword('')
    setConfirmPassword('')
    setFormError(null)
  }

  const handleSaveUser = async () => {
    setFormError(null)
    if (!username.trim()) return setFormError('用户名不能为空')
    if (!/^[A-Za-z0-9_-]+$/.test(username)) return setFormError('用户名只能包含字母、数字、下划线和短横线')
    if (!editUser) {
      if (password.length < 8) return setFormError('密码至少 8 位')
      if (password !== confirmPassword) return setFormError('两次密码输入不一致')
    }
    
    // 如果是修改角色，且是从别的角色修改，需要二次确认
    if (editUser && editUser.role !== role) {
      setConfirmAction({ type: 'changeRole', user: editUser, targetRole: role })
      return
    }

    // 如果是禁用用户，且原来是启用的，需要二次确认
    if (editUser && editUser.enabled && !enabled) {
      setConfirmAction({ type: 'disable', user: editUser })
      return
    }

    try {
      setSaving(true)
      if (editUser) {
        const updates: Partial<User> = {}
        if (role !== editUser.role) updates.role = role
        if (enabled !== editUser.enabled) updates.enabled = enabled
        if (mustChangePassword !== editUser.must_change_password) updates.must_change_password = mustChangePassword
        
        if (Object.keys(updates).length > 0) {
          await usersApi.updateUser(editUser.id, updates)
        }
      } else {
        await usersApi.createUser({ username, password, role, enabled, must_change_password: mustChangePassword })
      }
      closeForm()
      await fetchUsers()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleExecuteConfirm = async () => {
    if (!confirmAction) return
    setSaving(true)
    setPageError(null)
    const { type, user, targetRole } = confirmAction
    try {
      if (type === 'delete') {
        await usersApi.deleteUser(user.id)
      } else if (type === 'disable') {
        await usersApi.updateUser(user.id, { enabled: false })
        closeForm()
      } else if (type === 'changeRole') {
        await usersApi.updateUser(user.id, { role: targetRole! })
        closeForm()
      } else if (type === 'resetPassword') {
        await usersApi.resetPassword(user.id, { new_password: newPassword })
        setResetModalOpen(false)
        setNewPassword('')
        setResetConfirmPassword('')
      }
      await fetchUsers()
    } catch (err) {
      setPageError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setConfirmAction(null)
      setSaving(false)
    }
  }

  const handleDeleteClick = (u: User) => {
    setConfirmAction({ type: 'delete', user: u })
  }

  const openResetPassword = (u: User) => {
    setResetUser(u)
    setNewPassword('')
    setResetConfirmPassword('')
    setResetError(null)
    setResetModalOpen(true)
  }

  const handleResetPasswordSubmit = () => {
    setResetError(null)
    if (newPassword.length < 8) return setResetError('密码至少 8 位')
    if (newPassword !== resetConfirmPassword) return setResetError('两次密码输入不一致')
    setConfirmAction({ type: 'resetPassword', user: resetUser! })
  }

  const formatTime = (ts: string | null) => {
    if (!ts) return '从未'
    return new Date(ts).toLocaleString()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-black text-white">用户列表</h2>
          <p className="mt-1 text-sm text-zinc-400">管理系统账号与权限</p>
        </div>
        <ToolbarButton onClick={openCreate}>新增用户</ToolbarButton>
      </div>

      {pageError && <div className="rounded-lg bg-red-500/10 p-4 text-red-400">{pageError}</div>}

      <div className="rounded-2xl border border-white/10 bg-black/40 overflow-hidden">
        <table className="w-full text-left text-sm text-zinc-300">
          <thead className="bg-white/5 text-xs font-black uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-6 py-4">ID / 用户名</th>
              <th className="px-6 py-4">角色</th>
              <th className="px-6 py-4">状态</th>
              <th className="px-6 py-4 hidden md:table-cell">创建时间</th>
              <th className="px-6 py-4 hidden lg:table-cell">最近登录</th>
              <th className="px-6 py-4 text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {loading && users.length === 0 ? (
              <tr><td colSpan={6} className="px-6 py-8 text-center text-zinc-500">加载中...</td></tr>
            ) : users.length === 0 ? (
              <tr><td colSpan={6} className="px-6 py-8 text-center text-zinc-500">暂无数据</td></tr>
            ) : (
              users.map(u => (
                <tr key={u.id} className="hover:bg-white/[0.02] transition-colors">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <span className="text-zinc-500">#{u.id}</span>
                      <span className="font-mono text-white">{u.username}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span className="rounded border border-white/10 bg-white/5 px-2 py-1 text-[10px] font-black uppercase tracking-wider text-zinc-400">
                      {u.role}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <div className={`h-2 w-2 rounded-full ${u.enabled ? 'bg-green-500' : 'bg-red-500'}`} />
                      <span>{u.enabled ? '启用' : '禁用'}</span>
                      {u.must_change_password && <span className="text-yellow-500 text-xs ml-2">(须改密)</span>}
                    </div>
                  </td>
                  <td className="px-6 py-4 hidden md:table-cell text-zinc-500">{formatTime(u.created_at)}</td>
                  <td className="px-6 py-4 hidden lg:table-cell text-zinc-500">{formatTime(u.last_login_at)}</td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button onClick={() => openEdit(u)} className="text-xs hover:text-white transition-colors text-zinc-400">编辑</button>
                      <button onClick={() => openResetPassword(u)} className="text-xs hover:text-white transition-colors text-zinc-400">重置密码</button>
                      <button onClick={() => handleDeleteClick(u)} className="text-xs hover:text-red-400 transition-colors text-red-500">删除</button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {formOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-3xl border border-white/10 bg-zinc-950 p-6 shadow-2xl">
            <h3 className="text-lg font-black text-white mb-5">{editUser ? '编辑用户' : '新增用户'}</h3>
            {formError && <div className="mb-4 rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{formError}</div>}
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-black uppercase text-zinc-500 mb-1">用户名</label>
                <input 
                  type="text" 
                  value={username} 
                  onChange={e => setUsername(e.target.value)} 
                  disabled={!!editUser}
                  className="w-full rounded-xl border border-white/10 bg-black/50 px-4 py-2.5 text-sm text-white focus:border-blue-500/50 focus:outline-none disabled:opacity-50"
                  placeholder="登录名，不可包含特殊字符"
                />
              </div>
              
              {!editUser && (
                <>
                  <div>
                    <label className="block text-xs font-black uppercase text-zinc-500 mb-1">密码</label>
                    <input 
                      type="password" 
                      value={password} 
                      onChange={e => setPassword(e.target.value)} 
                      className="w-full rounded-xl border border-white/10 bg-black/50 px-4 py-2.5 text-sm text-white focus:border-blue-500/50 focus:outline-none"
                      placeholder="至少 8 位字符"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-black uppercase text-zinc-500 mb-1">确认密码</label>
                    <input 
                      type="password" 
                      value={confirmPassword} 
                      onChange={e => setConfirmPassword(e.target.value)} 
                      className="w-full rounded-xl border border-white/10 bg-black/50 px-4 py-2.5 text-sm text-white focus:border-blue-500/50 focus:outline-none"
                      placeholder="再次输入密码"
                    />
                  </div>
                </>
              )}

              <div>
                <label className="block text-xs font-black uppercase text-zinc-500 mb-1">角色权限</label>
                <select 
                  value={role} 
                  onChange={e => setRole(e.target.value as Role)}
                  className="w-full rounded-xl border border-white/10 bg-black/50 px-4 py-2.5 text-sm text-white focus:border-blue-500/50 focus:outline-none"
                >
                  <option value="viewer">Viewer (仅查看)</option>
                  <option value="operator">Operator (可控制机器人)</option>
                  <option value="admin">Admin (全部权限)</option>
                </select>
              </div>

              <div className="flex gap-6 mt-4">
                <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                  <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} className="h-4 w-4 accent-blue-500" />
                  允许登录
                </label>
                <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                  <input type="checkbox" checked={mustChangePassword} onChange={e => setMustChangePassword(e.target.checked)} className="h-4 w-4 accent-yellow-500" />
                  必须修改密码
                </label>
              </div>
            </div>

            <div className="mt-8 flex justify-end gap-3">
              <ToolbarButton onClick={closeForm} disabled={saving}>取消</ToolbarButton>
              <ToolbarButton onClick={handleSaveUser} disabled={saving}>{saving ? '保存中...' : '保存'}</ToolbarButton>
            </div>
          </div>
        </div>
      )}

      {resetModalOpen && resetUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-3xl border border-white/10 bg-zinc-950 p-6 shadow-2xl">
            <h3 className="text-lg font-black text-white mb-2">重置密码</h3>
            <p className="text-sm text-zinc-400 mb-5">为用户「{resetUser.username}」设置新密码</p>
            {resetError && <div className="mb-4 rounded-lg bg-red-500/10 p-3 text-xs text-red-400">{resetError}</div>}
            <div className="space-y-4">
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
                  value={resetConfirmPassword} 
                  onChange={e => setResetConfirmPassword(e.target.value)} 
                  className="w-full rounded-xl border border-white/10 bg-black/50 px-4 py-2.5 text-sm text-white focus:border-blue-500/50 focus:outline-none"
                  placeholder="再次输入密码"
                />
              </div>
            </div>
            <div className="mt-8 flex justify-end gap-3">
              <ToolbarButton disabled={saving} onClick={() => {
                setResetModalOpen(false)
                setNewPassword('')
                setResetConfirmPassword('')
                setResetError(null)
              }}>取消</ToolbarButton>
              <ToolbarButton disabled={saving} onClick={handleResetPasswordSubmit}>确认重置</ToolbarButton>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!confirmAction}
        title={
          confirmAction?.type === 'delete' ? '确认删除用户' :
          confirmAction?.type === 'disable' ? '确认禁用用户' :
          confirmAction?.type === 'changeRole' ? '确认修改角色' :
          '确认重置密码'
        }
        description={
          confirmAction?.type === 'delete' ? `即将软删除用户「${confirmAction.user.username}」。该用户将无法登录，但历史审计日志会保留。` :
          confirmAction?.type === 'disable' ? `即将禁用用户「${confirmAction.user.username}」。禁用后该用户无法登录，已发放的 Token 将失效。` :
          confirmAction?.type === 'changeRole' ? `即将把用户「${confirmAction.user.username}」的角色从 ${confirmAction.user.role} 修改为 ${confirmAction.targetRole}，权限范围会立即变化，旧 Token 将失效。` :
          confirmAction?.type === 'resetPassword' ? `即将重置用户「${confirmAction.user.username}」的密码。该用户已发放的 Token 将失效。` : ''
        }
        confirmText={saving ? '执行中...' : '确认操作'}
        onCancel={() => setConfirmAction(null)}
        onConfirm={handleExecuteConfirm}
        danger={confirmAction?.type === 'delete' || confirmAction?.type === 'disable'}
        disabled={saving}
      />
    </div>
  )
}
