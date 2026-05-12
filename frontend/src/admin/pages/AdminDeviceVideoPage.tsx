import { useState } from 'react'
import type { HealthResponse, SystemInfoGroup } from '../adminTypes'
import type { PcdSceneItem } from '../../types/pcdMap'
import type { SystemConfig } from '../../types/config'
import type { VideoSource, NetworkInterface } from '../../types/admin'
import type { NavStateResponse } from '../../types/navState'
import type { AIStatus, AutoTrackStatus } from '../../types/event'
import { AdminCard, ToolbarButton } from '../AdminUi'
import { AdminDevicePage } from './AdminDevicePage'
import { AdminVideoAiPage } from './AdminVideoAiPage'

interface AdminDeviceVideoPageProps {
  deviceData: {
    systemInfo: SystemInfoGroup[]
    networkInterfaces: NetworkInterface[]
    health: HealthResponse | null
    navState: NavStateResponse | null
    aiStatus: AIStatus | null
    autoTrackStatus: AutoTrackStatus | null
  }
  scenes: PcdSceneItem[]
  selectedSceneId: string | null
  onRefresh: () => void
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
  deviceData,
  scenes,
  selectedSceneId,
  onRefresh,
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
  const [tab, setTab] = useState<'device' | 'video'>('device')

  return (
    <div className="space-y-6">
      <AdminCard
        title="设备与视频"
        subtitle="保留真实可用的主机、网络和视频信息。"
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <ToolbarButton onClick={onRefresh}>刷新设备</ToolbarButton>
            <ToolbarButton onClick={onVideoRefresh}>刷新视频</ToolbarButton>
          </div>
        }
      >
        <div className="flex flex-wrap gap-3">
          <ToolbarButton onClick={() => setTab('device')} disabled={tab === 'device'}>设备管理</ToolbarButton>
          <ToolbarButton onClick={() => setTab('video')} disabled={tab === 'video'}>视频与 AI</ToolbarButton>
        </div>
      </AdminCard>

      {tab === 'device' ? (
        <AdminDevicePage
          data={deviceData}
          onRefresh={onRefresh}
        />
      ) : (
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
      )}

      <AdminCard
        title="地图与点位快捷入口"
        subtitle="地图、点位和巡逻任务仍统一放在导航管理。"
      >
        <div className="space-y-3">
          <div className="text-sm text-zinc-400">当前可用场景：{scenes.length}</div>
          <div className="text-sm text-zinc-400">当前选择场景：{selectedSceneId || '未选择'}</div>
          <div className="text-xs text-zinc-500">如需编辑地图点位，请切换到“导航管理”。</div>
        </div>
      </AdminCard>
    </div>
  )
}
