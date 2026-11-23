import { useEffect, useState } from 'react'
import { getGasMonitor, type GasAlarm } from '../api/gasMonitorApi'

export type GasMonitorState = {
  state: 'loading' | 'ready' | 'unavailable'
  alerts: GasAlarm[]
  error: string | null
}

export function useGasMonitor(): GasMonitorState {
  const [state, setState] = useState<GasMonitorState>({ state: 'loading', alerts: [], error: null })

  useEffect(() => {
    let stopped = false
    let pollTimer: ReturnType<typeof setTimeout>
    let expiryTimer: ReturnType<typeof setTimeout>
    let controller: AbortController

    const poll = async () => {
      controller = new AbortController()
      const deadline = setTimeout(() => controller.abort(), 5000)
      try {
        const result = await getGasMonitor(controller.signal)
        if (stopped) return
        clearTimeout(expiryTimer)
        setState({ state: 'ready', alerts: result.alerts, error: null })
        expiryTimer = setTimeout(() => {
          setState((previous) => ({ ...previous, state: 'unavailable', error: '气体监测数据未更新' }))
        }, 15000)
      } catch (error) {
        if (stopped) return
        clearTimeout(expiryTimer)
        setState((previous) => ({ ...previous, state: 'unavailable',
          error: controller.signal.aborted ? '气体监测请求超时' : error instanceof Error ? error.message : '气体监测连接异常' }))
      } finally {
        clearTimeout(deadline)
        if (!stopped) pollTimer = setTimeout(() => { void poll() }, 10000)
      }
    }

    void poll()
    return () => {
      stopped = true
      controller.abort()
      clearTimeout(pollTimer)
      clearTimeout(expiryTimer)
    }
  }, [])

  return state
}
