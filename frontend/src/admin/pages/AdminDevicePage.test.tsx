import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AdminDevicePage } from './AdminDevicePage'
import type { DeviceOverviewData } from '../adminTypes'

describe('live device readiness', () => {
  it('uses fresh health data instead of treating an old AI_STATUS as healthy', () => {
    const data: DeviceOverviewData = {
      systemInfo: [], networkInterfaces: [], navState: null, hostResources: null, autoTrackStatus: null,
      aiStatus: { frames_processed: 100, detections_count: 0, mode: 'idle', hits: 0, stable_hits: 5 },
      health: { status: 'degraded', mavlink_connected: false, uptime: 1, ready: false, readiness_status: 'standby', components: {
        video_ai: { ready: false, required: true, status: 'waiting', message: '视频未接入，等待设备' },
        control: { ready: false, required: true, status: 'waiting', message: '机器人未接入' },
        navigation: { ready: false, required: true, status: 'waiting', message: '等待定位' },
      } },
    }
    render(<AdminDevicePage data={data} onRefresh={() => {}} canManageSystem={false} />)
    expect(screen.getByText('后端接口在线')).toBeInTheDocument()
    expect(screen.getByText('视频未接入，等待设备')).toBeInTheDocument()
    expect(screen.queryByText('已收到 AI_STATUS，frames=100')).not.toBeInTheDocument()
    expect(screen.getByText('业务就绪')).toBeInTheDocument()
  })
})
