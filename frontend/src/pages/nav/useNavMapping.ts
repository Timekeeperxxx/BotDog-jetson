import { useCallback, useState } from 'react'
import { setMappingEnabled } from '../../api/pcdMapApi'

type MappingSessionInfo = {
  sceneName: string
  mapDir: string
}

function validateMappingSceneName(
  rawValue: string,
): { ok: false; message: string } | { ok: true; value: string } {
  const sceneName = rawValue.trim()
  if (!sceneName) {
    return { ok: false, message: '请输入场景名称' }
  }
  if (sceneName === '.' || sceneName === '..') {
    return { ok: false, message: '场景名称非法' }
  }
  if (sceneName.includes('/') || sceneName.includes('\\')) {
    return { ok: false, message: '场景名称不能包含 / 或 \\' }
  }
  if (sceneName.includes('..')) {
    return { ok: false, message: '场景名称不能包含 ..' }
  }
  if (Array.from(sceneName).some((char) => char.charCodeAt(0) < 32)) {
    return { ok: false, message: '场景名称包含非法控制字符' }
  }
  if (sceneName.length > 100) {
    return { ok: false, message: '场景名称过长' }
  }
  return { ok: true, value: sceneName }
}

type UseNavMappingOptions = {
  canOperate: boolean
  onLog: (message: string, level?: 'info' | 'error') => void
}

export function useNavMapping({ canOperate, onLog }: UseNavMappingOptions) {
  const [mappingActive, setMappingActive] = useState(false)
  const [mappingSending, setMappingSending] = useState(false)
  const [mappingDialogOpen, setMappingDialogOpen] = useState(false)
  const [mappingSceneName, setMappingSceneName] = useState('')
  const [mappingSceneError, setMappingSceneError] = useState<string | null>(null)
  const [mappingSessionInfo, setMappingSessionInfo] = useState<MappingSessionInfo | null>(null)

  const handleStopMapping = useCallback(async () => {
    if (!canOperate) return
    if (mappingSending) return

    setMappingSending(true)
    try {
      const result = await setMappingEnabled(false)
      setMappingActive(false)
      setMappingSessionInfo(null)
      onLog(result.message || '已停止建图')
    } catch (error) {
      onLog(error instanceof Error ? error.message : '停止建图失败', 'error')
    } finally {
      setMappingSending(false)
    }
  }, [canOperate, mappingSending, onLog])

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
      setMappingSessionInfo({
        sceneName: result.scene_name || validated.value,
        mapDir: result.map_dir || '',
      })
      setMappingDialogOpen(false)
      onLog(
        result.message
          ? `${result.message}：${result.scene_name}，目录=${result.map_dir}`
          : `建图已启动：${result.scene_name}，目录=${result.map_dir}`,
      )
    } catch (error) {
      const message = error instanceof Error ? error.message : '启动建图失败'
      onLog(message, 'error')
      if (message.includes('建图已在进行中')) {
        setMappingActive(true)
      }
    } finally {
      setMappingSending(false)
    }
  }, [canOperate, mappingSceneName, mappingSending, onLog])

  return {
    mappingActive,
    setMappingActive,
    mappingSending,
    mappingDialogOpen,
    setMappingDialogOpen,
    mappingSceneName,
    setMappingSceneName,
    mappingSceneError,
    setMappingSceneError,
    mappingSessionInfo,
    setMappingSessionInfo,
    handleStopMapping,
    handleOpenMappingDialog,
    handleConfirmStartMapping,
  }
}
