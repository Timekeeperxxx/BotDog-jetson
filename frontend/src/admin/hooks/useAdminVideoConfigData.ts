import { useCallback, useEffect, useMemo, useState } from 'react'
import { useConfig } from '../../hooks/useConfig'
import { useVideoSources } from '../../hooks/useVideoSources'
import type { VideoSource, VideoSourceRequest } from '../../types/admin'
import type { SystemConfig } from '../../types/config'

export type SourceFormState = {
  source_id?: number
  name: string
  label: string
  source_type: 'whep' | 'rtsp' | 'usb'
  whep_url: string
  rtsp_url: string
  enabled: boolean
  is_primary: boolean
  is_ai_source: boolean
  sort_order: number
}

function emptySourceForm(): SourceFormState {
  return {
    name: '',
    label: '',
    source_type: 'whep',
    whep_url: '',
    rtsp_url: '',
    enabled: true,
    is_primary: false,
    is_ai_source: false,
    sort_order: 0,
  }
}

function sourceToForm(source: VideoSource): SourceFormState {
  return {
    source_id: source.source_id,
    name: source.name,
    label: source.label,
    source_type: source.source_type,
    whep_url: source.whep_url || '',
    rtsp_url: source.rtsp_url || '',
    enabled: source.enabled,
    is_primary: source.is_primary,
    is_ai_source: source.is_ai_source,
    sort_order: source.sort_order,
  }
}

export function useAdminVideoConfigData() {
  const videoSources = useVideoSources()
  const configHook = useConfig()
  const { fetchSources, fetchInterfaces, deleteSource, createSource, updateSource } = videoSources
  const { fetchConfigs, updateConfig, configs } = configHook
  const [videoSearch, setVideoSearch] = useState('')
  const [sourceToDelete, setSourceToDelete] = useState<VideoSource | null>(null)
  const [sourceFormOpen, setSourceFormOpen] = useState(false)
  const [sourceForm, setSourceForm] = useState<SourceFormState>(emptySourceForm())

  const configList = useMemo<SystemConfig[]>(() => Object.values(configs), [configs])

  const openNewSource = useCallback(() => {
    setSourceForm(emptySourceForm())
    setSourceFormOpen(true)
  }, [])

  const openEditSource = useCallback((source: VideoSource) => {
    setSourceForm(sourceToForm(source))
    setSourceFormOpen(true)
  }, [])

  const closeSourceForm = useCallback(() => {
    setSourceFormOpen(false)
  }, [])

  const saveSource = useCallback(async () => {
    const payload: VideoSourceRequest = {
      name: sourceForm.name,
      label: sourceForm.label,
      source_type: sourceForm.source_type,
      whep_url: sourceForm.whep_url || null,
      rtsp_url: sourceForm.rtsp_url || null,
      enabled: sourceForm.enabled,
      is_primary: sourceForm.is_primary,
      is_ai_source: sourceForm.is_ai_source,
      sort_order: Number(sourceForm.sort_order) || 0,
    }

    if (sourceForm.source_id) {
      await updateSource(sourceForm.source_id, payload)
    } else {
      await createSource(payload)
    }

    setSourceFormOpen(false)
    await fetchSources()
  }, [createSource, fetchSources, sourceForm, updateSource])

  const deleteSelectedSource = useCallback(async () => {
    if (!sourceToDelete) return
    await deleteSource(sourceToDelete.source_id)
    await fetchSources()
  }, [deleteSource, fetchSources, sourceToDelete])

  const saveConfigValue = useCallback(async (key: string, value: string | boolean) => {
    await updateConfig(key, value)
    await fetchConfigs()
  }, [fetchConfigs, updateConfig])

  useEffect(() => {
    void fetchSources()
    void fetchInterfaces()
    void fetchConfigs()
  }, [fetchConfigs, fetchInterfaces, fetchSources])

  return {
    videoSources,
    configHook,
    configList,
    videoSearch,
    setVideoSearch,
    sourceToDelete,
    setSourceToDelete,
    sourceFormOpen,
    sourceForm,
    setSourceForm,
    openNewSource,
    openEditSource,
    closeSourceForm,
    saveSource,
    deleteSelectedSource,
    saveConfigValue,
  }
}
