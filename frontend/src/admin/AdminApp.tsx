import { useCallback, useEffect, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'
import { MapPinned, Network, RefreshCw } from 'lucide-react'
import { useEventWebSocket } from '../hooks/useEventWebSocket'
import { useNavWebSocket } from '../hooks/useNavWebSocket'
import { useVideoSources } from '../hooks/useVideoSources'
import { useConfig } from '../hooks/useConfig'
import { useEvidence } from '../hooks/useEvidence'
import { getNavState } from '../api/navApi'
import { deleteWaypoint, getPcdMetadata, listPcdMaps, listWaypoints } from '../api/pcdMapApi'
import type { NavWaypoint, PcdMapItem, PcdMetadata } from '../types/pcdMap'
import type { SystemConfig } from '../types/config'
import type { VideoSource, VideoSourceRequest } from '../types/admin'
import type { AdminLogEntry, HealthResponse, SystemInfoGroup, AdminSection } from './adminTypes'
import { getAdminLogs, getSystemHealth, getSystemInfo } from './adminApi'
import { ConfirmDialog, ToolbarButton } from './AdminUi'
import { AdminDashboardPage } from './pages/AdminDashboardPage'
import { AdminNavigationPage } from './pages/AdminNavigationPage'
import { AdminEvidencePage } from './pages/AdminEvidencePage'
import { AdminLogsPage } from './pages/AdminLogsPage'
import { AdminConfigPage } from './pages/AdminConfigPage'
import { AdminUsersPage } from './pages/AdminUsersPage'
import { AdminControlPage } from './pages/AdminControlPage'
import { AdminDeviceVideoPage } from './pages/AdminDeviceVideoPage'
import { AdminAiGuardPage } from './pages/AdminAiGuardPage'
import { AdminDiagnosticsPage } from './pages/AdminDiagnosticsPage'
import { AdminLayout } from './components/AdminLayout'
import { AdminHeader, type AdminHeaderStatusItem } from './components/AdminHeader'
import { AdminSidebar, type AdminRole } from './components/AdminSidebar'
import { adminNavItems, getVisibleSections } from './adminMenu'
import { useAuthState } from '../stores/authStore'
import type { TaskDefinition } from '../types/taskWorkflow'

const TASK_STORAGE_KEY = 'botdog-nav-workflows'

type SourceFormState = {
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

function readStoredTasks(): TaskDefinition[] {
  try {
    const raw = window.localStorage.getItem(TASK_STORAGE_KEY)
    if (!raw) return []
    return JSON.parse(raw) as TaskDefinition[]
  } catch {
    return []
  }
}

export function AdminApp() {
  const auth = useAuthState()
  const role = (auth.role ?? 'viewer') as AdminRole
  const [activeSection, setActiveSection] = useState<AdminSection>('dashboard')
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [systemInfo, setSystemInfo] = useState<SystemInfoGroup[]>([])
  const [logs, setLogs] = useState<AdminLogEntry[]>([])
  const [navState, setNavState] = useState<any>(null)
  const [maps, setMaps] = useState<PcdMapItem[]>([])
  const [selectedMapId, setSelectedMapId] = useState<string | null>(null)
  const [metadata, setMetadata] = useState<PcdMetadata | null>(null)
  const [waypoints, setWaypoints] = useState<NavWaypoint[]>([])
  const [tasks, setTasks] = useState<TaskDefinition[]>([])
  const [adminLoading, setAdminLoading] = useState(false)
  const [adminError, setAdminError] = useState<string | null>(null)
  const [navSearch, setNavSearch] = useState('')
  const [videoSearch, setVideoSearch] = useState('')
  const [evidenceSearch, setEvidenceSearch] = useState('')
  const [logSearch, setLogSearch] = useState('')
  const [waypointToDelete, setWaypointToDelete] = useState<NavWaypoint | null>(null)
  const [sourceToDelete, setSourceToDelete] = useState<VideoSource | null>(null)
  const [sourceFormOpen, setSourceFormOpen] = useState(false)
  const [sourceForm, setSourceForm] = useState<SourceFormState>(emptySourceForm())

  const eventState = useEventWebSocket()
  const navWs = useNavWebSocket()
  const videoSources = useVideoSources()
  const configHook = useConfig()
  const evidenceHook = useEvidence()
  const { fetchSources, fetchInterfaces } = videoSources
  const { fetchConfigs } = configHook
  const { fetchEvidence } = evidenceHook

  const refreshAdminCore = useCallback(async () => {
    setAdminLoading(true)
    setAdminError(null)
    try {
      const [nextHealth, nextInfo, nextLogs, nextNavState, nextMaps] = await Promise.all([
        getSystemHealth(),
        getSystemInfo(),
        getAdminLogs(),
        getNavState().catch(() => null),
        listPcdMaps().catch(() => ({ root: '', items: [] })),
      ])
      setHealth(nextHealth)
      setSystemInfo(nextInfo.groups || [])
      setLogs(nextLogs.items || [])
      setNavState(nextNavState)
      setMaps(nextMaps.items || [])
      setTasks(readStoredTasks())

      if (!selectedMapId && nextMaps.items.length > 0) {
        setSelectedMapId(nextMaps.items[0].id)
      }
    } catch (error) {
      setAdminError(error instanceof Error ? error.message : '后台数据加载失败')
    } finally {
      setAdminLoading(false)
    }
  }, [selectedMapId])

  const refreshMapDetails = useCallback(async (mapId: string) => {
    const [nextMetadata, nextWaypoints] = await Promise.all([
      getPcdMetadata(mapId).catch(() => null),
      listWaypoints(mapId).catch(() => ({ items: [] })),
    ])
    setMetadata(nextMetadata)
    setWaypoints(nextWaypoints.items || [])
  }, [])

  useEffect(() => {
    void refreshAdminCore()
    void fetchSources()
    void fetchInterfaces()
    void fetchEvidence()
  }, [fetchEvidence, fetchInterfaces, fetchSources, refreshAdminCore])

  useEffect(() => {
    if (activeSection !== 'device-video' && activeSection !== 'config') return
    if (Object.keys(configHook.configs).length > 0) return
    void fetchConfigs()
  }, [activeSection, configHook.configs, fetchConfigs])

  useEffect(() => {
    if (!selectedMapId) return
    void refreshMapDetails(selectedMapId)
  }, [refreshMapDetails, selectedMapId])

  useEffect(() => {
    if (!navState) return
    navWs.setInitialState({
      robotPose: navState.robot_pose,
      navigationStatus: navState.navigation_status,
      localizationStatus: navState.localization_status,
    })
  }, [navState])

  useEffect(() => {
    const visibleSections = getVisibleSections(role)
    if (!visibleSections.includes(activeSection)) {
      setActiveSection(visibleSections[0] ?? 'dashboard')
    }
  }, [activeSection, role])

  const mergedNavState = useMemo(() => ({
    robot_pose: navWs.robotPose ?? navState?.robot_pose ?? null,
    navigation_status: navWs.navigationStatus ?? navState?.navigation_status ?? { status: 'waiting', target_waypoint_id: null, target_name: null, message: '等待中', timestamp: null },
    localization_status: navWs.localizationStatus ?? navState?.localization_status ?? { status: 'waiting', frame_id: 'map', source: null, message: '等待中', timestamp: null },
  }), [navState, navWs.localizationStatus, navWs.navigationStatus, navWs.robotPose])

  const configList = useMemo<SystemConfig[]>(() => Object.values(configHook.configs), [configHook.configs])
  const sectionMeta = useMemo(
    () => adminNavItems.find((item) => item.key === activeSection) ?? adminNavItems[0],
    [activeSection],
  )

  const openNewSource = useCallback(() => {
    setSourceForm(emptySourceForm())
    setSourceFormOpen(true)
  }, [])

  const openEditSource = useCallback((source: VideoSource) => {
    setSourceForm(sourceToForm(source))
    setSourceFormOpen(true)
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
      await videoSources.updateSource(sourceForm.source_id, payload)
    } else {
      await videoSources.createSource(payload)
    }

    setSourceFormOpen(false)
    await videoSources.fetchSources()
  }, [sourceForm, videoSources])

  const saveConfigValue = useCallback(async (key: string, value: string | boolean) => {
    await configHook.updateConfig(key, value)
    await configHook.fetchConfigs()
  }, [configHook])

  const headerStatusItems = useMemo<AdminHeaderStatusItem[]>(() => [
    { icon: <Network size={14} />, label: '事件流', value: eventState.status.status },
    { icon: <MapPinned size={14} />, label: '导航', value: navWs.connected ? 'ws已连接' : 'ws离线' },
    { icon: <RefreshCw size={14} />, label: '健康状态', value: health?.status || '等待中' },
  ], [eventState.status.status, health?.status, navWs.connected])

  const headerActions = (
    <>
      <ToolbarButton
        onClick={() => window.location.assign('/operator')}
        disabled={role === 'viewer'}
        title={role === 'viewer' ? '需要 operator 权限' : undefined}
      >
        进入操作台
      </ToolbarButton>
      <ToolbarButton onClick={() => void refreshAdminCore()}>{adminLoading ? '刷新中' : '刷新总览'}</ToolbarButton>
    </>
  )

  const content = useMemo(() => {
    if (activeSection === 'dashboard') {
      return (
        <AdminDashboardPage
          data={{
            health,
            navState: mergedNavState,
            aiStatus: eventState.aiStatus,
            autoTrackStatus: eventState.autoTrackStatus,
            alerts: eventState.alerts,
            logs,
            evidence: evidenceHook.evidenceItems,
            videoSources: videoSources.sources,
          }}
        />
      )
    }

    if (activeSection === 'control') {
      return (
        <AdminControlPage
          health={health}
          navState={mergedNavState}
          onOpenOperator={() => window.location.assign('/operator')}
          onOpenPatrol={() => window.location.assign('/nav-patrol.html')}
        />
      )
    }

    if (activeSection === 'navigation') {
      return (
        <AdminNavigationPage
          maps={maps}
          selectedMapId={selectedMapId}
          metadata={metadata}
          waypoints={waypoints}
          tasks={tasks}
          loading={adminLoading}
          search={navSearch}
          onSearchChange={setNavSearch}
          onRefresh={() => {
            void refreshAdminCore()
            if (selectedMapId) void refreshMapDetails(selectedMapId)
          }}
          onSelectMap={setSelectedMapId}
          onDeleteWaypoint={setWaypointToDelete}
          canOperate={role !== 'viewer'}
        />
      )
    }

    if (activeSection === 'device-video') {
      return (
        <AdminDeviceVideoPage
          deviceData={{
            systemInfo,
            networkInterfaces: videoSources.interfaces,
            health,
            navState: mergedNavState,
            aiStatus: eventState.aiStatus,
            autoTrackStatus: eventState.autoTrackStatus,
          }}
          maps={maps}
          selectedMapId={selectedMapId}
          onRefresh={() => {
            void refreshAdminCore()
            void videoSources.fetchInterfaces()
          }}
          videoSources={videoSources.sources}
          configs={configList}
          videoLoading={videoSources.loading || configHook.loading}
          videoSearch={videoSearch}
          onVideoSearchChange={setVideoSearch}
          onVideoRefresh={() => {
            void videoSources.fetchSources()
            void configHook.fetchConfigs()
          }}
          onCreateSource={openNewSource}
          onEditSource={openEditSource}
          onDeleteSource={setSourceToDelete}
          onSaveConfig={saveConfigValue}
        />
      )
    }

    if (activeSection === 'ai-guard') {
      return (
        <AdminAiGuardPage
          health={health}
          aiStatus={eventState.aiStatus}
          autoTrackStatus={eventState.autoTrackStatus}
          navState={mergedNavState}
          logs={logs}
          videoSources={videoSources.sources}
          onOpenOperator={() => window.location.assign('/operator')}
        />
      )
    }

    if (activeSection === 'evidence') {
      return (
        <AdminEvidencePage
          evidence={evidenceHook.evidenceItems}
          loading={evidenceHook.evidenceLoading}
          search={evidenceSearch}
          onSearchChange={setEvidenceSearch}
          onRefresh={() => void evidenceHook.fetchEvidence()}
          onDelete={async (item) => {
            await evidenceHook.deleteEvidenceByIds([item.evidence_id])
          }}
        />
      )
    }

    if (activeSection === 'logs') {
      return (
        <AdminLogsPage
          logs={logs}
          loading={adminLoading}
          search={logSearch}
          onSearchChange={setLogSearch}
          onRefresh={() => void refreshAdminCore()}
        />
      )
    }

    if (activeSection === 'users') {
      return <AdminUsersPage />
    }

    if (activeSection === 'diagnostics') {
      return <AdminDiagnosticsPage onOpenPatrol={() => window.location.assign('/nav-patrol.html')} />
    }

    return <AdminConfigPage configHook={configHook} />
  }, [
    activeSection,
    adminLoading,
    configHook,
    configHook.loading,
    configList,
    evidenceHook,
    evidenceSearch,
    eventState.aiStatus,
    eventState.alerts,
    eventState.autoTrackStatus,
    health,
    logs,
    maps,
    mergedNavState,
    metadata,
    navSearch,
    openEditSource,
    openNewSource,
    refreshAdminCore,
    refreshMapDetails,
    saveConfigValue,
    selectedMapId,
    systemInfo,
    tasks,
    videoSearch,
    videoSources,
    waypoints,
    role,
  ])

  return (
    <AdminLayout
      sidebar={<AdminSidebar items={adminNavItems} activeSection={activeSection} onSectionChange={setActiveSection} role={role} />}
      header={
        <AdminHeader
          title={sectionMeta.label}
          description={sectionMeta.description}
          statusItems={headerStatusItems}
          actions={headerActions}
          error={adminError}
          mobileItems={adminNavItems}
          role={role}
          activeSection={activeSection}
          onSectionChange={setActiveSection}
        />
      }
    >
      {content}

      <ConfirmDialog
        open={waypointToDelete !== null}
        title="确认删除导航点"
        description={waypointToDelete
          ? [
            `点位名称：${waypointToDelete.name}`,
            `waypoint_id：${waypointToDelete.id}`,
            `map_id：${waypointToDelete.map_id}`,
            `位置：${waypointToDelete.x.toFixed(2)} / ${waypointToDelete.y.toFixed(2)} / ${waypointToDelete.z.toFixed(2)}`,
            `yaw：${waypointToDelete.yaw.toFixed(3)}`,
            '提示：该操作会修改地图对应的 JSON 存储，不可恢复。',
          ].join('\n')
          : ''}
        confirmText="确认删除"
        onCancel={() => setWaypointToDelete(null)}
        onConfirm={() => {
          if (!waypointToDelete || !selectedMapId) return
          void deleteWaypoint(selectedMapId, waypointToDelete.id).then(() => refreshMapDetails(selectedMapId))
          setWaypointToDelete(null)
        }}
        danger
      />

      <ConfirmDialog
        open={sourceToDelete !== null}
        title="确认删除视频源"
        description={sourceToDelete
          ? [
            `source_id：${sourceToDelete.source_id}`,
            `name：${sourceToDelete.name}`,
            `label：${sourceToDelete.label}`,
            `type：${sourceToDelete.source_type}`,
            `WHEP：${sourceToDelete.whep_url || '--'}`,
            `RTSP：${sourceToDelete.rtsp_url || '--'}`,
            '提示：删除后操作台相关视频源不可用，该操作不可恢复。',
          ].join('\n')
          : ''}
        confirmText="确认删除"
        onCancel={() => setSourceToDelete(null)}
        onConfirm={() => {
          if (!sourceToDelete) return
          void videoSources.deleteSource(sourceToDelete.source_id).then(() => videoSources.fetchSources())
          setSourceToDelete(null)
        }}
        danger
      />

      {sourceFormOpen ? (
        <SourceFormModal
          form={sourceForm}
          onChange={setSourceForm}
          onClose={() => setSourceFormOpen(false)}
          onSubmit={() => void saveSource()}
          loading={videoSources.loading}
        />
      ) : null}
    </AdminLayout>
  )
}

function SourceFormModal({
  form,
  onChange,
  onClose,
  onSubmit,
  loading,
}: {
  form: SourceFormState
  onChange: Dispatch<SetStateAction<SourceFormState>>
  onClose: () => void
  onSubmit: () => void
  loading: boolean
}) {
  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
      <div className="w-full max-w-3xl rounded-3xl border border-white/10 bg-zinc-950 p-6 shadow-[0_30px_120px_-30px_rgba(0,0,0,0.9)]">
        <div className="text-lg font-black text-white">{form.source_id ? '编辑视频源' : '新增视频源'}</div>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <Field label="名称">
            <input value={form.name} onChange={(event) => onChange((prev) => ({ ...prev, name: event.target.value }))} className="field-input" />
          </Field>
          <Field label="标签">
            <input value={form.label} onChange={(event) => onChange((prev) => ({ ...prev, label: event.target.value }))} className="field-input" />
          </Field>
          <Field label="source_type">
            <select value={form.source_type} onChange={(event) => onChange((prev) => ({ ...prev, source_type: event.target.value as SourceFormState['source_type'] }))} className="field-input">
              <option value="whep">whep</option>
              <option value="rtsp">rtsp</option>
              <option value="usb">usb</option>
            </select>
          </Field>
          <Field label="sort_order">
            <input value={String(form.sort_order)} onChange={(event) => onChange((prev) => ({ ...prev, sort_order: Number(event.target.value) || 0 }))} className="field-input" />
          </Field>
          <Field label="WHEP URL">
            <input value={form.whep_url} onChange={(event) => onChange((prev) => ({ ...prev, whep_url: event.target.value }))} className="field-input" />
          </Field>
          <Field label="RTSP URL">
            <input value={form.rtsp_url} onChange={(event) => onChange((prev) => ({ ...prev, rtsp_url: event.target.value }))} className="field-input" />
          </Field>
        </div>
        <div className="mt-5 flex flex-wrap gap-5">
          <CheckField label="启用" checked={form.enabled} onChange={(checked) => onChange((prev) => ({ ...prev, enabled: checked }))} />
          <CheckField label="主摄像头" checked={form.is_primary} onChange={(checked) => onChange((prev) => ({ ...prev, is_primary: checked }))} />
          <CheckField label="AI 源" checked={form.is_ai_source} onChange={(checked) => onChange((prev) => ({ ...prev, is_ai_source: checked }))} />
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <ToolbarButton onClick={onClose}>取消</ToolbarButton>
          <ToolbarButton onClick={onSubmit} disabled={loading || !form.name || !form.label}>
            {loading ? '保存中' : '保存'}
          </ToolbarButton>
        </div>
      </div>
    </div>
  )
}

function Field({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <label className="block">
      <div className="mb-2 text-[10px] font-black uppercase tracking-[0.18em] text-zinc-500">{label}</div>
      {children}
    </label>
  )
}

function CheckField({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="flex items-center gap-3 text-sm text-zinc-200">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="h-4 w-4 accent-white" />
      <span>{label}</span>
    </label>
  )
}
