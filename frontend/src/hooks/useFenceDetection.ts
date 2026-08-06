import { useCallback, useEffect, useState } from 'react'
import {
  disableFenceDetection,
  enableFenceDetection,
  getFenceDetectionStatus,
} from '../api/fenceDetectionApi'
import type { FenceDetectionStatus } from '../types/fenceDetection'

export function useFenceDetection() {
  const [status, setStatus] = useState<FenceDetectionStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async (reportError = false) => {
    try {
      const next = await getFenceDetectionStatus()
      setStatus(next)
      if (reportError) setError(null)
    } catch (caught) {
      if (reportError) {
        setError(caught instanceof Error ? caught.message : '读取围栏检测状态失败')
      }
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const poll = async (reportError = false) => {
      if (cancelled) return
      await refresh(reportError)
    }
    void poll(true)
    const timer = window.setInterval(() => void poll(), 750)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [refresh])

  const setEnabled = useCallback(async (enabled: boolean) => {
    if (loading) return
    setLoading(true)
    setError(null)
    try {
      const next = enabled
        ? await enableFenceDetection()
        : await disableFenceDetection()
      setStatus(next)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : `${enabled ? '开启' : '关闭'}围栏检测失败`)
    } finally {
      setLoading(false)
    }
  }, [loading])

  return { status, loading, error, setEnabled, refresh }
}
