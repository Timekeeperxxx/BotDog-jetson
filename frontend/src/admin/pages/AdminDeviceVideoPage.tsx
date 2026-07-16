import type { SystemConfig } from '../../types/config'
import type { VideoSource } from '../../types/admin'
import { AdminVideoAiPage } from './AdminVideoAiPage'

interface AdminDeviceVideoPageProps {
  videoSources: VideoSource[]
  configs: SystemConfig[]
  videoLoading: boolean
  videoSearch: string
  onVideoSearchChange: (value: string) => void
  onVideoRefresh: () => void
  onCreateSource: () => void
  onEditSource: (source: VideoSource) => void
  onDeleteSource: (source: VideoSource) => void
  onSaveConfig: (key: string, value: string | boolean) => Promise<void>
}

export function AdminDeviceVideoPage({
  videoSources,
  configs,
  videoLoading,
  videoSearch,
  onVideoSearchChange,
  onVideoRefresh,
  onCreateSource,
  onEditSource,
  onDeleteSource,
  onSaveConfig,
}: AdminDeviceVideoPageProps) {
  return (
    <AdminVideoAiPage
      videoSources={videoSources}
      configs={configs}
      loading={videoLoading}
      search={videoSearch}
      onSearchChange={onVideoSearchChange}
      onRefresh={onVideoRefresh}
      onCreateSource={onCreateSource}
      onEditSource={onEditSource}
      onDeleteSource={onDeleteSource}
      onSaveConfig={onSaveConfig}
    />
  )
}
