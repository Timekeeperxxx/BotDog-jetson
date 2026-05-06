import { useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './styles/pcdMapDemo.css'
import { PcdMapDemoPage } from './pages/PcdMapDemoPage'
import { LoginPage } from './pages/LoginPage'
import {
  bootstrapAuthState,
  hasAuthSession,
  installAuthFetchInterceptor,
  useAuthState,
} from './stores/authStore'

// 在模块加载时立即安装 fetch 拦截器，确保所有 /api/ 请求都携带 Authorization
installAuthFetchInterceptor()

function NavPatrolAuthRoot() {
  const auth = useAuthState()

  useEffect(() => {
    void bootstrapAuthState()
  }, [])

  // 正在校验 token（ready=false, validating=true）
  if (!auth.ready && auth.validating) {
    return (
      <div className="min-h-screen bg-[#050506] text-white flex items-center justify-center px-6">
        <div className="border border-white/10 bg-black/70 px-6 py-5 text-sm text-zinc-300">
          正在校验登录状态...
        </div>
      </div>
    )
  }

  // 未登录：显示登录页，登录成功后 onSuccess 不传（默认 undefined），
  // 但 setAuthState 会触发 useAuthState 订阅更新，NavPatrolAuthRoot 重新渲染，
  // hasAuthSession() 变为 true，自动切换到 PcdMapDemoPage
  if (!hasAuthSession()) {
    return (
      <LoginPage
        onSuccess={() => {
          // 登录成功后无需跳转，NavPatrolAuthRoot 会因 auth 状态变化自动重渲染
        }}
      />
    )
  }

  return <PcdMapDemoPage />
}

createRoot(document.getElementById('nav-patrol-root')!).render(
  <NavPatrolAuthRoot />,
)
