import { useEffect, useState } from 'react'
import { getLocalizationDiagnostics, type LocalizationDiagnostics } from '../../api/pcdMapApi'

export function useLocalizationDiagnostics(sceneId: string | null, enabled: boolean) {
  const [diagnostic, setDiagnostic] = useState<LocalizationDiagnostics | null>(null)
  useEffect(() => {
    setDiagnostic(null)
    if (!enabled || !sceneId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    async function poll() {
      try {
        const result = await getLocalizationDiagnostics()
        if (!cancelled) setDiagnostic(result.scene_id && result.scene_id !== sceneId ? null : result)
      } catch (error) {
        if (!cancelled) setDiagnostic({
          scene_id: sceneId, phase: 'connection', level: 'error', match: null,
          navigation_ready: false, events: [],
          message: `[通信层] 无法获取最新定位诊断，当前状态未知：${error instanceof Error ? error.message : '请求失败'}；正在重试。`,
        })
      } finally {
        if (!cancelled) timer = setTimeout(() => void poll(), 1500)
      }
    }
    void poll()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [sceneId, enabled])
  return enabled && diagnostic?.scene_id !== undefined && (!diagnostic.scene_id || diagnostic.scene_id === sceneId)
    ? diagnostic : null
}
