/**
 * BotDog Industrial Horizon - 重构版
 * 保留完整的前后端交互、WebSocket连接和WHEP视频流
 * 采用新布局：左侧导航 + 顶部状态栏 + 中央视频(HUD) + 右侧栏(日志+AI)
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useBotDogWebSocket } from './hooks/useBotDogWebSocket';
import { useWhepVideo } from './hooks/useWhepVideo';
import { useEventWebSocket } from './hooks/useEventWebSocket';
import { useAutoTrack } from './hooks/useAutoTrack';
import { useEvidence } from './hooks/useEvidence';
import { useMissionControl } from './hooks/useMissionControl';
import { useAudioControl } from './hooks/useAudioControl';
import { useGuardMissionControl } from './hooks/useGuardMissionControl';
import { useCameraSources } from './hooks/useCameraSources';
import { useFullscreenControl } from './hooks/useFullscreenControl';
import { useWebSocketStatusLogger } from './hooks/useWebSocketStatusLogger';
import { useWhepStatusLogger } from './hooks/useWhepStatusLogger';
import { useVideoReconnectEffects } from './hooks/useVideoReconnectEffects';
import { useStartupLog } from './hooks/useStartupLog';
import { getApiUrl } from './config/api';
import { Sidebar, type SidebarTab } from './components/layout/Sidebar';
import { TopHeader } from './components/layout/TopHeader';
import { AuthStatusBar } from './components/AuthStatusBar';
import { EvidencePanel } from './components/evidence/EvidencePanel';
import { ConsolePage } from './components/pages/ConsolePage';
import { GuardPage } from './components/pages/GuardPage';
import { ConfigModal } from './components/modals/ConfigModal';
import type { VideoProfile } from './components/video/types';

function buildLocalWhepUrl(path: string): string {
  return `http://${window.location.hostname}:8889/${path}/whep`;
}

// ==================== 主应用 ====================
export default function IndustrialConsoleComplete() {
  const {
    telemetry,
    isConnected,
    systemStatus,
    logs,
    addLog,
    connect: connectWs,
    disconnect: disconnectWs,
  } = useBotDogWebSocket();

  // 事件流由 main.tsx 中的 EventStreamProvider 自动连接，这里只消费派生状态。
  const { alerts, latestAlert, aiStatus, autoTrackStatus, trackDecision, trackOverlay } = useEventWebSocket();

  const autoTrack = useAutoTrack(autoTrackStatus, trackDecision);

  const sidebarLogEndRef = useRef<HTMLDivElement | null>(null);

  const { frontWhepUrl, omniUrls } = useCameraSources();
  const remoteWhepUrl = useMemo(() => buildLocalWhepUrl('cam_remote'), []);
  const [videoProfile, setVideoProfile] = useState<VideoProfile>('main');
  const selectedWhepUrl = videoProfile === 'remote' ? remoteWhepUrl : frontWhepUrl;

  const {
    status: whepStatus,
    videoRef,
    videoLatencyMs,
    videoLatencyStats,
    videoResolution,
    connect: connectWhep,
    disconnect: disconnectWhep,
  } = useWhepVideo(selectedWhepUrl);

  const [showConfigPanel, setShowConfigPanel] = useState(false);
  const [activeTab, setActiveTab] = useState<SidebarTab>('console');
  const [isLogExpanded, setIsLogExpanded] = useState(false);
  const [isAiStatsExpanded, setIsAiStatsExpanded] = useState(false);

  const evidence = useEvidence();
  const { fetchEvidence } = evidence;
  const { missionTaskId, isMissionRunning, toggleMission } = useMissionControl(addLog);
  const { isAudioPlaying, toggleAudio } = useAudioControl();
  const { guardStatus, toggleGuardMission, abortGuardMission } = useGuardMissionControl();
  const { isUiFullscreen, toggleFullscreen } = useFullscreenControl();

  const openNavPatrolPage = useCallback(() => {
    window.open('/nav-patrol.html', '_blank', 'noopener,noreferrer');
  }, []);

  const openAdminPage = useCallback(() => {
    window.location.assign('/admin');
  }, []);

  const triggerSnapshot = useCallback(async () => {
    try {
      const url = missionTaskId
        ? getApiUrl(`/api/v1/snapshot?task_id=${missionTaskId}`)
        : getApiUrl('/api/v1/snapshot');
      const res = await fetch(url, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        addLog(`拍照失败: ${err.detail ?? res.statusText}`, 'error', 'SNAPSHOT');
        return;
      }
      addLog('拍照成功，已保存至证据库', 'info', 'SNAPSHOT');
    } catch (err) {
      addLog(`拍照请求失败: ${err}`, 'error', 'SNAPSHOT');
    }
  }, [missionTaskId, addLog]);

  const [isRecording, setIsRecording] = useState(false);

  const toggleRecording = useCallback(async () => {
    const endpoint = isRecording ? '/api/v1/recording/stop' : '/api/v1/recording/start';
    try {
      const res = await fetch(getApiUrl(endpoint), { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        addLog(`录像操作失败: ${err.detail ?? res.statusText}`, 'error', 'RECORDING');
        return;
      }
      if (isRecording) {
        addLog('录像已停止，已保存至录像库', 'info', 'RECORDING');
        setIsRecording(false);
      } else {
        addLog('录像已开始', 'info', 'RECORDING');
        setIsRecording(true);
      }
    } catch (err) {
      addLog(`录像请求失败: ${err}`, 'error', 'RECORDING');
    }
  }, [isRecording, addLog]);

  // WebSocket 连接
  useEffect(() => { connectWs(); return () => { disconnectWs(); }; }, [connectWs, disconnectWs]);

  useEffect(() => {
    if (activeTab !== 'history') return;
    void fetchEvidence();
  }, [activeTab, fetchEvidence]);

  useVideoReconnectEffects({
    activeTab,
    connectWhep,
    disconnectWhep,
  });
  useStartupLog(addLog);
  useWebSocketStatusLogger(isConnected, addLog);
  useWhepStatusLogger(whepStatus, addLog);

  const resolutionChip = videoResolution.height ? `${videoResolution.height}p` : '--';

  const whepConfig: Record<string, { color: string; text: string }> = {
    disconnected: { color: 'text-red-500', text: '未连接' },
    connecting: { color: 'text-amber-500', text: '连接中...' },
    connected: { color: 'text-emerald-500', text: '已连接' },
    error: { color: 'text-red-500', text: whepStatus.error || '错误' },
  };
  const currentWhep = whepConfig[whepStatus.status] || whepConfig.disconnected;

  return (
    <div className="flex h-screen w-full bg-[#050506] text-white font-sans overflow-hidden antialiased selection:bg-white selection:text-black">
      <AuthStatusBar variant="overlay" />
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        onOpenNavPatrolPage={openNavPatrolPage}
        onOpenAdminPage={openAdminPage}
        onOpenConfig={() => setShowConfigPanel(true)}
        latestAlert={latestAlert}
        isUiFullscreen={isUiFullscreen}
      />

      {/* 主视图 */}
      <main className="flex-1 flex flex-col min-w-0 relative">
        <h1 className="sr-only">BotDog 智能巡检控制台</h1>
        <TopHeader
          isUiFullscreen={isUiFullscreen}
          isMissionRunning={isMissionRunning}
          telemetry={telemetry}
          isConnected={isConnected}
          videoLatencyMs={videoLatencyMs}
        />

        {activeTab === 'console' ? (
          <ConsolePage
            isUiFullscreen={isUiFullscreen}
            videoStageProps={{
              videoRef,
              isUiFullscreen,
              toggleFullscreen,
              trackOverlay,
              autoTrackEnabled: autoTrack.status?.enabled ?? false,
              guardEnabled: guardStatus?.enabled ?? false,
              whepStatus,
              currentWhep,
              videoLatencyMs,
              videoLatencyStats,
              videoResolution,
              resolutionChip,
              telemetry,
              isConnected,
              aiStatus,
              autoTrackFrames: autoTrack.status?.frames_processed ?? 0,
              autoTrack,
              connectWs,
              connectWhep,
              isMissionRunning,
              triggerSnapshot,
              toggleMission,
              frontWhepUrl,
              omniUrls,
              isRecording,
              onToggleRecording: toggleRecording,
              videoProfile,
              onVideoProfileChange: setVideoProfile,
            }}
            rightPanelProps={{
              logs,
              isLogExpanded,
              onToggleLogExpanded: () => setIsLogExpanded(!isLogExpanded),
              sidebarLogEndRef,
              systemStatus,
              isAudioPlaying,
              toggleAudio,
              aiStatus,
              isAiStatsExpanded,
              onToggleAiStatsExpanded: () => setIsAiStatsExpanded(v => !v),
              isMissionRunning,
              toggleMission,
              isConnected,
              whepStatus,
              alerts,
              connectWs,
              connectWhep,
            }}
          />
        ) : activeTab === 'guard' ? (
          <GuardPage
            videoRef={videoRef}
            whepStatus={whepStatus}
            connectWhep={connectWhep}
            videoLatencyMs={videoLatencyMs}
            trackOverlay={trackOverlay}
            guardStatus={guardStatus}
            onToggleEnable={toggleGuardMission}
            onEmergencyStop={abortGuardMission}
            logs={logs}
            isAudioPlaying={isAudioPlaying}
            onAudioToggle={toggleAudio}
          />
        ) : (
          <EvidencePanel evidence={evidence} />
        )}
      </main>

      {/* 配置面板模态框 */}
      <ConfigModal isOpen={showConfigPanel} onClose={() => setShowConfigPanel(false)} />
    </div>
  );
}
