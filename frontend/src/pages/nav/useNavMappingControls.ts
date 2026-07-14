import { useCallback, useEffect, useState } from 'react'
import {
  getMappingStatus,
  setMappingEnabled,
} from '../../api/pcdMapApi'
import type { LogItem, MappingSessionInfo } from './navPageUtils'
import { validateMappingSceneName } from './navPageUtils'

export const MIN_MAPPING_RUNTIME_SECONDS = 90

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

  const handleStopMapping = useCallback(async (options?: { skipMinRuntimeCheck?: boolean }) => {
    if (!canOperate) return
    if (mappingSending) return

    if (!options?.skipMinRuntimeCheck && mappingStartTime != null) {
      const elapsed = (Date.now() - mappingStartTime) / 1000
      if (elapsed < MIN_MAPPING_RUNTIME_SECONDS) {
        setMappingStopConfirmOpen(true)
        return
      }
    }

    setMappingStopConfirmOpen(false)
    setMappingSending(true)
    try {
      const result = await setMappingEnabled(false)
      setMappingActive(false)
      setMappingSessionInfo(null)
      setMappingStartTime(null)

      if (result.saved) {
        addLog(result.message || '地图已保存')
        setTimeout(() => {
          void refreshScenes()
        }, 500)
      } else {
        const missing: string[] = []
        if (result.map_pcd_candidates.length === 0) missing.push('map.pcd')
        if (result.ground_pcd_candidates.length === 0) missing.push('ground.pcd')
        addLog(
          `地图保存不完整：缺少 ${missing.join('、')}，请查看 start_mapping_debug.log`,
          'error',
        )
      }
    } catch (error) {
      addLog(error instanceof Error ? error.message : '停止建图失败', 'error')
    } finally {
      setMappingSending(false)
    }
  }, [addLog, canOperate, mappingSending, mappingStartTime, refreshScenes])

  const handleOpenMappingDialog = useCallback(() => {
    if (!canOperate) return
    if (mappingSending) return
    setMappingSceneError(null)
    setMappingSceneName('')
    setMappingDialogOpen(true)
  }, [canOperate, mappingSending])

  const handleConfirmStartMapping = useCallback(async () => {
    if (!canOperate) return
    if (mappingSending) return

    const validated = validateMappingSceneName(mappingSceneName)
    if (!validated.ok) {
      setMappingSceneError(validated.message)
      return
    }

    setMappingSceneError(null)
    setMappingSending(true)
    try {
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
      const message = error instanceof Error ? error.message : '启动建图失败'
      addLog(message, 'error')
      if (message.includes('建图已在进行中')) {
        setMappingActive(true)
      }
    } finally {
      setMappingSending(false)
    }
  }, [addLog, canOperate, mappingSceneName, mappingSending])

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
    mappingSceneError,
    mappingSceneName,
    mappingSending,
    mappingSessionInfo,
    mappingStopConfirmOpen,
    setMappingSceneError,
    setMappingSceneName,
    setMappingStopConfirmOpen,
  }
}
