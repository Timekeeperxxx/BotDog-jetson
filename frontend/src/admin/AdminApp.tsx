import { useEffect, useMemo, useState } from 'react'
import { useEventWebSocket } from '../hooks/useEventWebSocket'
import { useNavWebSocket } from '../hooks/useNavWebSocket'
import type { AdminSection } from './adminTypes'
import { AdminLayout } from './components/AdminLayout'
import { AdminHeader } from './components/AdminHeader'
import { AdminSidebar, type AdminRole } from './components/AdminSidebar'
import { AdminModalsHost } from './components/AdminModalsHost'
import { adminNavItems, getVisibleSections } from './adminMenu'
import { useAuthState } from '../stores/authStore'
import { useAdminCoreData } from './hooks/useAdminCoreData'
import { useAdminEvidenceData } from './hooks/useAdminEvidenceData'
import { useAdminNavigationData } from './hooks/useAdminNavigationData'
import { useAdminVideoConfigData } from './hooks/useAdminVideoConfigData'
import { useAdminHeader } from './hooks/useAdminHeader'
import { AdminContentSwitch } from './components/AdminContentSwitch'

export function AdminApp() {
  const auth = useAuthState()
  const role = (auth.role ?? 'viewer') as AdminRole
  const [activeSection, setActiveSection] = useState<AdminSection>('dashboard')
  const coreData = useAdminCoreData()
  const navigationData = useAdminNavigationData()
  const videoConfigData = useAdminVideoConfigData()
  const evidenceData = useAdminEvidenceData()
  const [logSearch, setLogSearch] = useState('')

  // 事件流由 main.tsx 中的 EventStreamProvider 自动连接，这里只读取状态。
  const eventState = useEventWebSocket()
  const navWs = useNavWebSocket()
  const { setInitialState } = navWs
  const { health, navState, adminLoading, adminError } = coreData
  const { selectedSceneId, waypointToDelete, setWaypointToDelete, deleteSelectedWaypoint } = navigationData
  const { sourceToDelete, setSourceToDelete, sourceFormOpen, sourceForm, setSourceForm, closeSourceForm, deleteSelectedSource } = videoConfigData
  const { refreshAdminCore } = coreData

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
      queueMicrotask(() => {
        setActiveSection(visibleSections[0] ?? 'dashboard')
      })
    }
  }, [activeSection, role])

  const mergedNavState = useMemo(() => ({
    robot_pose: navWs.robotPose ?? navState?.robot_pose ?? null,
    global_path: navWs.globalPath ?? navState?.global_path ?? null,
    navigation_status: navWs.navigationStatus ?? navState?.navigation_status ?? { status: 'waiting', target_waypoint_id: null, target_name: null, message: '等待中', timestamp: null },
    localization_status: navWs.localizationStatus ?? navState?.localization_status ?? { status: 'waiting', frame_id: 'map', source: null, message: '等待中', timestamp: null },
  }), [navState, navWs.globalPath, navWs.localizationStatus, navWs.navigationStatus, navWs.robotPose])

  const { sectionMeta, headerStatusItems, headerActions } = useAdminHeader({
    activeSection,
    role,
    eventState,
    navConnected: navWs.connected,
    healthStatus: health?.status,
    adminLoading,
    refreshAdminCore,
  })

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
      <AdminContentSwitch
        activeSection={activeSection}
        role={role}
        coreData={coreData}
        navigationData={navigationData}
        videoConfigData={videoConfigData}
        evidenceData={evidenceData}
        eventState={eventState}
        mergedNavState={mergedNavState}
        logSearch={logSearch}
        setLogSearch={setLogSearch}
      />
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
        onSubmitSourceForm={() => void videoConfigData.saveSource()}
        sourceLoading={videoConfigData.videoSources.loading}
      />
    </AdminLayout>
  )
}
