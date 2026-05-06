import { useState } from 'react'
import type { HealthResponse, SystemInfoGroup } from '../adminTypes'
import type { PcdMapItem } from '../../types/pcdMap'
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
  maps: PcdMapItem[]
  selectedMapId: string | null
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
  maps,
  selectedMapId,
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
        subtitle="把主机信息、网络接口、视频源和 AI 配置放在同一模块下，方便统一排查。"
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
        subtitle="直接复用导航管理中的地图、点位和巡逻任务数据，不重复做一套管理界面。"
      >
        <div className="space-y-3">
          <div className="text-sm text-zinc-400">当前可用地图：{maps.length}</div>
          <div className="text-sm text-zinc-400">当前选择地图：{selectedMapId || '未选择'}</div>
          <div className="text-xs text-zinc-500">如需编辑地图点位，请切换到“导航管理”模块。</div>
        </div>
      </AdminCard>
    </div>
  )
}
