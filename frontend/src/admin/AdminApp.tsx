import { useEffect, useMemo, useState } from 'react'
import { MapPinned, Network, RefreshCw } from 'lucide-react'
import { useEventWebSocket } from '../hooks/useEventWebSocket'
import { useNavWebSocket } from '../hooks/useNavWebSocket'
import type { AdminSection } from './adminTypes'
import { ToolbarButton } from './AdminUi'
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
import { AdminModalsHost } from './components/AdminModalsHost'
import { adminNavItems, getVisibleSections } from './adminMenu'
import { useAuthState } from '../stores/authStore'
import { useAdminCoreData } from './hooks/useAdminCoreData'
import { useAdminEvidenceData } from './hooks/useAdminEvidenceData'
import { useAdminNavigationData } from './hooks/useAdminNavigationData'
import { useAdminVideoConfigData } from './hooks/useAdminVideoConfigData'

export function AdminApp() {
  const auth = useAuthState()
  const role = (auth.role ?? 'viewer') as AdminRole
  const [activeSection, setActiveSection] = useState<AdminSection>('dashboard')
  const {
    health,
    systemInfo,
    logs,
    navState,
    adminLoading,
    adminError,
    refreshAdminCore,
  } = useAdminCoreData()
  const {
    scenes,
    selectedSceneId,
    setSelectedSceneId,
    metadata,
    waypoints,
    tasks,
    navSearch,
    setNavSearch,
    waypointToDelete,
    setWaypointToDelete,
    refreshNavigationData,
    refreshSceneDetails,
    deleteSelectedWaypoint,
  } = useAdminNavigationData()
  const {
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
  } = useAdminVideoConfigData()
  const {
    evidenceHook,
    evidenceSearch,
    setEvidenceSearch,
    refreshEvidence,
    deleteEvidenceItem,
  } = useAdminEvidenceData()
  const [logSearch, setLogSearch] = useState('')

  const eventState = useEventWebSocket()
  const navWs = useNavWebSocket()
  const { setInitialState } = navWs

  useEffect(() => {
    if (!navState) return
    setInitialState({
      robotPose: navState.robot_pose,
      globalPath: navState.global_path,
      navigationStatus: navState.navigation_status,
      localizationStatus: navState.localization_status,
    })
  }, [navState, setInitialState])

  useEffect(() => {
    const visibleSections = getVisibleSections(role)
    if (!visibleSections.includes(activeSection)) {
      setActiveSection(visibleSections[0] ?? 'dashboard')
    }
  }, [activeSection, role])

  const mergedNavState = useMemo(() => ({
    robot_pose: navWs.robotPose ?? navState?.robot_pose ?? null,
    global_path: navWs.globalPath ?? navState?.global_path ?? null,
    navigation_status: navWs.navigationStatus ?? navState?.navigation_status ?? { status: 'waiting', target_waypoint_id: null, target_name: null, message: '等待中', timestamp: null },
    localization_status: navWs.localizationStatus ?? navState?.localization_status ?? { status: 'waiting', frame_id: 'map', source: null, message: '等待中', timestamp: null },
  }), [navState, navWs.globalPath, navWs.localizationStatus, navWs.navigationStatus, navWs.robotPose])

  const sectionMeta = useMemo(
    () => adminNavItems.find((item) => item.key === activeSection) ?? adminNavItems[0],
    [activeSection],
  )

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
          scenes={scenes}
          selectedSceneId={selectedSceneId}
          metadata={metadata}
          waypoints={waypoints}
          tasks={tasks}
          loading={adminLoading}
          search={navSearch}
          onSearchChange={setNavSearch}
          onRefresh={() => {
            void refreshNavigationData()
            void refreshAdminCore()
            if (selectedSceneId) void refreshSceneDetails(selectedSceneId)
          }}
          onSelectScene={setSelectedSceneId}
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
          scenes={scenes}
          selectedSceneId={selectedSceneId}
          onRefresh={() => {
            void refreshAdminCore()
            void videoSources.fetchInterfaces()
            void videoSources.fetchSources()
            void configHook.fetchConfigs()
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
          onRefresh={() => void refreshEvidence()}
          onDelete={deleteEvidenceItem}
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
    deleteEvidenceItem,
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
    scenes,
    mergedNavState,
    metadata,
    navSearch,
    openEditSource,
    openNewSource,
    refreshAdminCore,
    refreshEvidence,
    refreshNavigationData,
    refreshSceneDetails,
    saveConfigValue,
    setEvidenceSearch,
    setNavSearch,
    selectedSceneId,
    systemInfo,
    setSourceToDelete,
    setSelectedSceneId,
    setSourceForm,
    setVideoSearch,
    setWaypointToDelete,
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
          activeSection={activeSection}
          onSectionChange={setActiveSection}
          mobileItems={adminNavItems}
          role={role}
        />
      }
    >
      {content}
      <AdminModalsHost
        waypointToDelete={waypointToDelete}
        selectedSceneId={selectedSceneId}
        onCancelDeleteWaypoint={() => setWaypointToDelete(null)}
        onConfirmDeleteWaypoint={() => {
          void deleteSelectedWaypoint()
          setWaypointToDelete(null)
        }}
        sourceToDelete={sourceToDelete}
        onCancelDeleteSource={() => setSourceToDelete(null)}
        onConfirmDeleteSource={() => {
          void deleteSelectedSource()
          setSourceToDelete(null)
        }}
        sourceFormOpen={sourceFormOpen}
        sourceForm={sourceForm}
        onSourceFormChange={setSourceForm}
        onCloseSourceForm={closeSourceForm}
        onSubmitSourceForm={() => void saveSource()}
        sourceLoading={videoSources.loading}
      />
    </AdminLayout>
  )
}
