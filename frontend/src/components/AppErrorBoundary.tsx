import { Component, type ErrorInfo, type ReactNode } from 'react'

type AppErrorBoundaryProps = {
  children: ReactNode
}

type AppErrorBoundaryState = {
  failed: boolean
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { failed: false }

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('页面渲染失败', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children

    return (
      <main className="flex min-h-screen items-center justify-center bg-[#050506] px-6 text-white">
        <section className="w-full max-w-lg rounded-xl border border-red-500/30 bg-zinc-950 p-7 shadow-2xl" role="alert">
          <h1 className="text-xl font-black">页面发生异常</h1>
          <p className="mt-3 text-sm leading-6 text-zinc-300">
            当前页面无法继续显示。设备后台不一定受影响，请刷新页面重新建立连接。
          </p>
          <button
            type="button"
            className="mt-6 rounded-lg border border-white/20 bg-white px-4 py-2 text-sm font-bold text-black"
            onClick={() => window.location.reload()}
          >
            刷新页面
          </button>
        </section>
      </main>
    )
  }
}
