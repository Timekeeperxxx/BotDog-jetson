import type { Dispatch, SetStateAction } from 'react'
import type { EventHookState } from '../../hooks/useEventWebSocket'
import type { AdminSection } from '../adminTypes'
import type { AdminRole } from './AdminSidebar'
import { AdminDashboardPage } from '../pages/AdminDashboardPage'
import { AdminNavigationPage } from '../pages/AdminNavigationPage'
import { AdminEvidencePage } from '../pages/AdminEvidencePage'
import { AdminLogsPage } from '../pages/AdminLogsPage'
import { AdminConfigPage } from '../pages/AdminConfigPage'
import { AdminUsersPage } from '../pages/AdminUsersPage'
import { AdminControlPage } from '../pages/AdminControlPage'
import { AdminDeviceVideoPage } from '../pages/AdminDeviceVideoPage'
import { AdminAiGuardPage } from '../pages/AdminAiGuardPage'
import { AdminDiagnosticsPage } from '../pages/AdminDiagnosticsPage'
import type { useAdminCoreData } from '../hooks/useAdminCoreData'
import type { useAdminNavigationData } from '../hooks/useAdminNavigationData'
import type { useAdminVideoConfigData } from '../hooks/useAdminVideoConfigData'
import type { useAdminEvidenceData } from '../hooks/useAdminEvidenceData'
import type { NavStateResponse } from '../../types/navState'

type AdminCoreData = ReturnType<typeof useAdminCoreData>
type AdminNavigationData = ReturnType<typeof useAdminNavigationData>
type AdminVideoConfigData = ReturnType<typeof useAdminVideoConfigData>
type AdminEvidenceData = ReturnType<typeof useAdminEvidenceData>

type AdminContentSwitchProps = {
  activeSection: AdminSection
  role: AdminRole
  coreData: AdminCoreData
  navigationData: AdminNavigationData
  videoConfigData: AdminVideoConfigData
  evidenceData: AdminEvidenceData
  eventState: EventHookState
  mergedNavState: NavStateResponse
  logSearch: string
  setLogSearch: Dispatch<SetStateAction<string>>
}

export function AdminContentSwitch({
  activeSection,
  role,
  coreData,
  navigationData,
  videoConfigData,
  evidenceData,
  eventState,
  mergedNavState,
  logSearch,
  setLogSearch,
}: AdminContentSwitchProps) {
  const canOperate = role !== 'viewer'

  if (activeSection === 'dashboard') {
    return (
      <AdminDashboardPage
        data={{
          health: coreData.health,
          navState: mergedNavState,
          aiStatus: eventState.aiStatus,
          autoTrackStatus: eventState.autoTrackStatus,
          alerts: eventState.alerts,
          logs: coreData.logs,
          evidence: evidenceData.evidenceHook.evidenceItems,
          videoSources: videoConfigData.videoSources.sources,
        }}
      />
    )
  }

  if (activeSection === 'control') {
    return (
      <AdminControlPage
        health={coreData.health}
        navState={mergedNavState}
        onOpenOperator={() => window.location.assign('/operator')}
        onOpenPatrol={() => window.location.assign('/nav-patrol.html')}
      />
    )
  }

  if (activeSection === 'navigation') {
    return (
      <AdminNavigationPage
        scenes={navigationData.scenes}
        selectedSceneId={navigationData.selectedSceneId}
        metadata={navigationData.metadata}
        waypoints={navigationData.waypoints}
        tasks={navigationData.tasks}
        loading={coreData.adminLoading}
        search={navigationData.navSearch}
        onSearchChange={navigationData.setNavSearch}
        onRefresh={() => {
          void navigationData.refreshNavigationData()
          void coreData.refreshAdminCore()
          if (navigationData.selectedSceneId) void navigationData.refreshSceneDetails(navigationData.selectedSceneId)
        }}
        onSelectScene={navigationData.setSelectedSceneId}
        onDeleteWaypoint={navigationData.setWaypointToDelete}
        canOperate={canOperate}
      />
    )
  }

  if (activeSection === 'device-video') {
    return (
      <AdminDeviceVideoPage
        deviceData={{
          systemInfo: coreData.systemInfo,
          networkInterfaces: videoConfigData.videoSources.interfaces,
          health: coreData.health,
          navState: mergedNavState,
          aiStatus: eventState.aiStatus,
          autoTrackStatus: eventState.autoTrackStatus,
        }}
        scenes={navigationData.scenes}
        selectedSceneId={navigationData.selectedSceneId}
        onRefresh={() => {
          void coreData.refreshAdminCore()
          void videoConfigData.videoSources.fetchInterfaces()
          void videoConfigData.videoSources.fetchSources()
          void videoConfigData.configHook.fetchConfigs()
        }}
        videoSources={videoConfigData.videoSources.sources}
        configs={videoConfigData.configList}
        videoLoading={videoConfigData.videoSources.loading || videoConfigData.configHook.loading}
        videoSearch={videoConfigData.videoSearch}
        onVideoSearchChange={videoConfigData.setVideoSearch}
        onVideoRefresh={() => {
          void videoConfigData.videoSources.fetchSources()
          void videoConfigData.configHook.fetchConfigs()
        }}
        onCreateSource={videoConfigData.openNewSource}
        onEditSource={videoConfigData.openEditSource}
        onDeleteSource={videoConfigData.setSourceToDelete}
        onSaveConfig={videoConfigData.saveConfigValue}
      />
    )
  }

  if (activeSection === 'ai-guard') {
    return (
      <AdminAiGuardPage
        health={coreData.health}
        aiStatus={eventState.aiStatus}
        autoTrackStatus={eventState.autoTrackStatus}
        navState={mergedNavState}
        logs={coreData.logs}
        videoSources={videoConfigData.videoSources.sources}
        onOpenOperator={() => window.location.assign('/operator')}
      />
    )
  }

  if (activeSection === 'evidence') {
    return (
      <AdminEvidencePage
        evidence={evidenceData.evidenceHook.evidenceItems}
        loading={evidenceData.evidenceHook.evidenceLoading}
        search={evidenceData.evidenceSearch}
        onSearchChange={evidenceData.setEvidenceSearch}
        onRefresh={() => void evidenceData.refreshEvidence()}
        onDelete={evidenceData.deleteEvidenceItem}
      />
    )
  }

  if (activeSection === 'logs') {
    return (
      <AdminLogsPage
        logs={coreData.logs}
        loading={coreData.adminLoading}
        search={logSearch}
        onSearchChange={setLogSearch}
        onRefresh={() => void coreData.refreshAdminCore()}
      />
    )
  }

  if (activeSection === 'users') {
    return <AdminUsersPage />
  }

  if (activeSection === 'diagnostics') {
    return <AdminDiagnosticsPage onOpenPatrol={() => window.location.assign('/nav-patrol.html')} />
  }

  return <AdminConfigPage configHook={videoConfigData.configHook} />
}
