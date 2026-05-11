import { useCallback, useState, type Dispatch, type SetStateAction } from 'react'
import { detectWebGLSupport } from '../../components/pcd/webglSupport'

type UseNavViewStateOptions = {
  addMode: boolean
  setAddMode: Dispatch<SetStateAction<boolean>>
  onLog: (message: string, level?: 'info' | 'error') => void
}

export function useNavViewState({ addMode, setAddMode, onLog }: UseNavViewStateOptions) {
  const [infoOpen, setInfoOpen] = useState(true)
  const [followRobot, setFollowRobot] = useState(false)
  const [toolMode, setToolMode] = useState<'none' | 'obstacle' | 'pose'>('none')
  const [waypointZ, setWaypointZ] = useState(-0.83)
  const [mouseMapPosition, setMouseMapPosition] = useState<{ x: number; y: number } | null>(null)
  const [webglSupported] = useState(() => detectWebGLSupport())

  const handleToolMode = useCallback((nextMode: 'obstacle' | 'pose') => {
    setToolMode((current) => {
      const resolved = current === nextMode ? 'none' : nextMode
      if (resolved !== 'none') {
        setAddMode(false)
      }
      onLog(
        resolved === 'none'
          ? '已退出工具模式'
          : resolved === 'obstacle'
            ? '已切换到添加障碍物模式'
            : '已切换到设置位姿模式',
      )
      return resolved
    })
  }, [onLog, setAddMode])

  const handleToggleFollowRobot = useCallback(() => {
    setFollowRobot((value) => {
      const nextValue = !value
      onLog(nextValue ? '已开启视角跟随' : '已关闭视角跟随')
      return nextValue
    })
  }, [onLog])

  const clearToolMode = useCallback(() => {
    setToolMode('none')
  }, [])

  const interactionMode: 'none' | 'waypoint' | 'pose' =
    addMode ? 'waypoint' : (toolMode === 'pose' ? 'pose' : 'none')

  return {
    infoOpen,
    setInfoOpen,
    followRobot,
    handleToggleFollowRobot,
    toolMode,
    clearToolMode,
    waypointZ,
    setWaypointZ,
    mouseMapPosition,
    setMouseMapPosition,
    webglSupported,
    handleToolMode,
    interactionMode,
  }
}
