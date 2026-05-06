import { useEffect, useState } from 'react'
import { login } from '../api/auth'
import { hasAuthSession, setAuthState, useAuthState } from '../stores/authStore'

export function LoginPage() {
  const auth = useAuthState()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (hasAuthSession()) {
      window.location.assign('/')
    }
  }, [auth.accessToken, auth.authBypass, auth.role])

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const result = await login(username, password)
      setAuthState({
        accessToken: result.access_token,
        username: result.user.username,
        role: result.user.role,
      })
      window.location.assign('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败，请检查用户名或密码')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#050506] text-white flex items-center justify-center px-6">
      <form onSubmit={handleSubmit} className="w-full max-w-md border border-white/10 bg-black/70 p-8 space-y-5">
        <div className="space-y-2">
          <div className="text-xs uppercase tracking-[0.35em] text-zinc-500">BotDog Auth</div>
          <h1 className="text-2xl font-black tracking-tight">登录控制台</h1>
          <p className="text-sm text-zinc-400">控制、配置和删除类操作需要先登录。</p>
        </div>

        <label className="block space-y-2">
          <span className="text-xs uppercase tracking-[0.2em] text-zinc-400">用户名</span>
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            className="w-full border border-white/10 bg-zinc-950 px-4 py-3 outline-none focus:border-white/30"
            autoComplete="username"
          />
        </label>

        <label className="block space-y-2">
          <span className="text-xs uppercase tracking-[0.2em] text-zinc-400">密码</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="w-full border border-white/10 bg-zinc-950 px-4 py-3 outline-none focus:border-white/30"
            autoComplete="current-password"
          />
        </label>

        {error ? <div className="text-sm text-red-400">{error}</div> : null}

        <button
          type="submit"
          disabled={loading}
          className="w-full border border-white bg-white text-black px-4 py-3 font-black uppercase tracking-[0.18em] disabled:opacity-50"
        >
          {loading ? '登录中' : '登录'}
        </button>
      </form>
    </div>
  )
}
