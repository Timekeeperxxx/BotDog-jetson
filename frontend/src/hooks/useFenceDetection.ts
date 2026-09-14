import { useCallback, useEffect, useState } from 'react'
import {
  getFenceDetectionStatus,
} from '../api/fenceDetectionApi'
import type { FenceDetectionStatus } from '../types/fenceDetection'

export function useFenceDetection() {
  const [status, setStatus] = useState<FenceDetectionStatus | null>(null)
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

  return { status, error }
}
