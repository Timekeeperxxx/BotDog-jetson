import { useCallback, useEffect, useState } from 'react'
import {
  checkRadarPreflight,
  getMappingStatus,
  setMappingEnabled,
} from '../../api/pcdMapApi'
import type { LogItem, MappingSessionInfo } from './navPageUtils'
import { validateMappingSceneName } from './navPageUtils'

export const MIN_MAPPING_RUNTIME_SECONDS = 90
const RADAR_PREFLIGHT_TIMEOUT_MS = 6000

type UseNavMappingControlsOptions = {
  addLog: (message: string, level?: LogItem['level']) => void
  canOperate: boolean
  refreshScenes: () => Promise<void>
}

export function useNavMappingControls({
  addLog,
  canOperate,
  refreshScenes,
}: UseNavMappingControlsOptions) {
  const [mappingActive, setMappingActive] = useState(false)
  const [mappingSending, setMappingSending] = useState(false)
  const [mappingPreflightChecking, setMappingPreflightChecking] = useState(false)
  const [mappingSaving, setMappingSaving] = useState(false)
  const [mappingDialogOpen, setMappingDialogOpen] = useState(false)
  const [mappingSceneName, setMappingSceneName] = useState('')
  const [mappingSceneError, setMappingSceneError] = useState<string | null>(null)
  const [mappingSessionInfo, setMappingSessionInfo] = useState<MappingSessionInfo | null>(null)
  const [mappingStartTime, setMappingStartTime] = useState<number | null>(null)
  const [mappingStopConfirmOpen, setMappingStopConfirmOpen] = useState(false)

  useEffect(() => {
    if (!canOperate) return
    let cancelled = false

    const syncMappingStatus = async () => {
      try {
        const status = await getMappingStatus()
        if (cancelled) return
        if (status.saving) {
          setMappingActive(false)
          setMappingSaving(true)
          setMappingSessionInfo({
            sceneName: status.scene_name || '未命名场景',
            mapDir: status.map_dir || '',
          })
          setMappingStartTime(null)
          addLog(status.message || '检测到后端正在保存地图，已恢复保存进度')
          return
        }
        if (!status.running) {
          return
        }

        setMappingActive(true)
        setMappingSessionInfo({
          sceneName: status.scene_name || '未命名场景',
          mapDir: status.map_dir || '',
        })
        setMappingStartTime(status.started_at ? status.started_at * 1000 : Date.now())
        addLog(status.message || '检测到后端建图正在运行，已恢复实时点云预览')
      } catch (error) {
        if (!cancelled) {
          addLog(error instanceof Error ? error.message : '读取建图状态失败', 'error')
        }
      }
    }

    void syncMappingStatus()
    return () => {
      cancelled = true
    }
  }, [addLog, canOperate])

  const applySaveResult = useCallback((result: Awaited<ReturnType<typeof getMappingStatus>>) => {
    if (result.saved) {
      addLog(result.message || '地图已保存')
      setTimeout(() => {
        void refreshScenes()
      }, 500)
    } else {
      const missing: string[] = []
      if (result.map_pcd_candidates.length === 0) missing.push('有效 map.pcd')
      if (result.ground_pcd_candidates.length === 0) missing.push('有效 ground.pcd')
      addLog(
        result.message || `地图保存不完整：缺少 ${missing.join('、')}，请查看 start_mapping_debug.log`,
        'error',
      )
    }
    setMappingSessionInfo(null)
    setMappingSaving(false)
    setMappingSending(false)
  }, [addLog, refreshScenes])

  useEffect(() => {
    if (!canOperate || !mappingSaving) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const pollSaveStatus = async () => {
      try {
        const status = await getMappingStatus()
        if (cancelled) return
        if (status.saving) {
          timer = setTimeout(() => {
            void pollSaveStatus()
          }, 2000)
          return
        }
        applySaveResult(status)
      } catch (error) {
        if (cancelled) return
        addLog(error instanceof Error ? error.message : '读取地图保存状态失败，将继续重试', 'error')
        timer = setTimeout(() => {
          void pollSaveStatus()
        }, 3000)
      }
    }

    timer = setTimeout(() => {
      void pollSaveStatus()
    }, 500)
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [addLog, applySaveResult, canOperate, mappingSaving])

  const handleStopMapping = useCallback(async (options?: { skipMinRuntimeCheck?: boolean }) => {
    if (!canOperate) return
    if (mappingSending || mappingSaving) return

    if (!options?.skipMinRuntimeCheck && mappingStartTime != null) {
      const elapsed = (Date.now() - mappingStartTime) / 1000
      if (elapsed < MIN_MAPPING_RUNTIME_SECONDS) {
        setMappingStopConfirmOpen(true)
        return
      }
    }

    setMappingStopConfirmOpen(false)
    // 用户确认结束后立即退出前端建图模式并断开实时点云。
    // 地图文件仍由后端继续保存，不能让最长 30 分钟的保存等待阻塞前端视图。
    setMappingActive(false)
    setMappingStartTime(null)
    setMappingSaving(true)
    setMappingSending(true)
    addLog('前端实时建图已停止，后台正在保存地图')
    try {
      const result = await setMappingEnabled(false)
      if (!result.saving) applySaveResult(result)
    } catch (error) {
      addLog(error instanceof Error ? error.message : '停止建图失败', 'error')
      setMappingSessionInfo(null)
      setMappingSaving(false)
    } finally {
      setMappingSending(false)
    }
  }, [addLog, applySaveResult, canOperate, mappingSaving, mappingSending, mappingStartTime])

  const handleOpenMappingDialog = useCallback(() => {
    if (!canOperate) return
    if (mappingSending || mappingSaving) return
    setMappingSceneError(null)
    setMappingSceneName('')
    setMappingDialogOpen(true)
  }, [canOperate, mappingSaving, mappingSending])

  const handleConfirmStartMapping = useCallback(async () => {
    if (!canOperate) return
    if (mappingSending || mappingSaving) return

    const validated = validateMappingSceneName(mappingSceneName)
    if (!validated.ok) {
      setMappingSceneError(validated.message)
      return
    }

    setMappingSceneError(null)
    setMappingSending(true)
    try {
      const preflightController = new AbortController()
      const preflightTimeout = window.setTimeout(() => {
        preflightController.abort()
      }, RADAR_PREFLIGHT_TIMEOUT_MS)
      let radarHealth
      setMappingPreflightChecking(true)
      try {
        radarHealth = await checkRadarPreflight(preflightController.signal)
      } finally {
        setMappingPreflightChecking(false)
        window.clearTimeout(preflightTimeout)
      }
      if (!radarHealth.ok) {
        const message = radarHealth.message || '雷达连接异常，已阻止启动建图'
        setMappingSceneError(message)
        addLog(`建图未启动：${message}`, 'error')
        return
      }

      const result = await setMappingEnabled(true, validated.value)
      setMappingActive(true)
      setMappingStartTime(Date.now())
      setMappingSessionInfo({
        sceneName: result.scene_name || validated.value,
        mapDir: result.map_dir || '',
      })
      setMappingDialogOpen(false)
      addLog(
        result.message
          ? `${result.message}：${result.scene_name}，目录=${result.map_dir}`
          : `建图已启动：${result.scene_name}，目录=${result.map_dir}`,
      )
    } catch (error) {
      const message = error instanceof Error && error.name === 'AbortError'
        ? '雷达健康检查超时，已阻止启动建图，请检查雷达连接'
        : error instanceof Error ? error.message : '启动建图失败'
      setMappingSceneError(message)
      addLog(message, 'error')
      if (message.includes('建图已在进行中')) {
        setMappingActive(true)
      }
    } finally {
      setMappingPreflightChecking(false)
      setMappingSending(false)
    }
  }, [addLog, canOperate, mappingSaving, mappingSceneName, mappingSending])

  const handleToggleMapping = useCallback(() => {
    if (mappingActive) {
      void handleStopMapping()
      return
    }
    handleOpenMappingDialog()
  }, [handleOpenMappingDialog, handleStopMapping, mappingActive])

  const closeMappingDialog = useCallback(() => {
    setMappingDialogOpen(false)
    setMappingSceneError(null)
  }, [])

  const confirmStopMapping = useCallback(() => {
    setMappingStopConfirmOpen(false)
    void handleStopMapping({ skipMinRuntimeCheck: true })
  }, [handleStopMapping])

  return {
    closeMappingDialog,
    confirmStopMapping,
    handleConfirmStartMapping,
    handleToggleMapping,
    mappingActive,
    mappingDialogOpen,
    mappingPreflightChecking,
    mappingSceneError,
    mappingSceneName,
    mappingSaving,
    mappingSending,
    mappingSessionInfo,
    mappingStopConfirmOpen,
    setMappingSceneError,
    setMappingSceneName,
    setMappingStopConfirmOpen,
  }
}
