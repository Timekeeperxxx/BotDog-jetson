import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from 'react'
import {
  notifyNavPageOpen,
  restartNavigationLocalization,
  triggerNavEmergencyStop,
} from '../../api/pcdMapApi'
import type { GlobalPath, NavigationStatus } from '../../types/navState'

type InitialStatePayload = {
  globalPath?: GlobalPath | null
  navigationStatus?: NavigationStatus | null
}

type UseNavRuntimeActionsOptions = {
  canOperate: boolean
  setNavigatingWaypointId: Dispatch<SetStateAction<string | null>>
  setInitialState: (state: InitialStatePayload) => void
  onLog: (message: string, level?: 'info' | 'error') => void
}

export function useNavRuntimeActions({
  canOperate,
  setNavigatingWaypointId,
  setInitialState,
  onLog,
}: UseNavRuntimeActionsOptions) {
  const [estopSending, setEstopSending] = useState(false)
  const [restartLocalizationSending, setRestartLocalizationSending] = useState(false)

  const handleEmergencyStop = useCallback(async () => {
    if (!canOperate) return
    if (estopSending) return

    setEstopSending(true)
    try {
      const result = await triggerNavEmergencyStop()
      setNavigatingWaypointId(null)
      setInitialState({
        globalPath: null,
        navigationStatus: {
          status: 'idle',
          target_waypoint_id: null,
          target_name: null,
          message: '已执行导航急停',
          timestamp: Date.now() / 1000,
        },
      })
      onLog(`已执行导航急停：${result.message}`, 'error')
    } catch (error) {
      onLog(error instanceof Error ? error.message : '执行导航急停失败', 'error')
    } finally {
      setEstopSending(false)
    }
  }, [canOperate, estopSending, onLog, setInitialState, setNavigatingWaypointId])

  const handleRestartNavigationLocalization = useCallback(async () => {
    if (!canOperate) return
    if (restartLocalizationSending) return

    setRestartLocalizationSending(true)
    try {
      const result = await restartNavigationLocalization()
      onLog(
        `导航定位已重启：${result.scene_id ?? '--'}，map=${result.map_pcd ?? '--'}，ground=${result.ground_pcd ?? '--'}，` +
          `livox=${result.livox_pid ?? 'null'}，relocation=${result.relocation_pid ?? 'null'}，` +
          `global_planner=${result.global_planner_pid ?? 'null'}，p2p_move_base=${result.p2p_move_base_pid ?? 'null'}，` +
          `cmd_vel=${result.cmd_vel_pid ?? 'null'}，ready=${result.navigation_ready ?? false}`,
      )
    } catch (error) {
      onLog(error instanceof Error ? error.message : '重启导航定位失败', 'error')
    } finally {
      setRestartLocalizationSending(false)
    }
  }, [canOperate, onLog, restartLocalizationSending])

  useEffect(() => {
    let cancelled = false

    async function sendPageOpenSignal() {
      try {
        const result = await notifyNavPageOpen()
        if (!cancelled) {
          onLog(`已发送页面启动信号到 ${result.topic}`)
        }
      } catch (error) {
        if (!cancelled) {
          onLog(error instanceof Error ? error.message : '发送页面启动信号失败', 'error')
        }
      }
    }

    void sendPageOpenSignal()
    return () => {
      cancelled = true
    }
  }, [onLog])

  return {
    estopSending,
    restartLocalizationSending,
    handleEmergencyStop,
    handleRestartNavigationLocalization,
  }
}
