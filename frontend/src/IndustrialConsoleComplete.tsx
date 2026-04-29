/**
 * BotDog Industrial Horizon - 重构版
 * 保留完整的前后端交互、WebSocket连接和WHEP视频流
 * 采用新布局：左侧导航 + 顶部状态栏 + 中央视频(HUD) + 右侧栏(日志+AI)
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useBotDogWebSocket } from './hooks/useBotDogWebSocket';
import { useWhepVideo } from './hooks/useWhepVideo';
import { AdminPanel } from './components/AdminPanel';
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
import { Sidebar, type SidebarTab } from './components/layout/Sidebar';
import { TopHeader } from './components/layout/TopHeader';
import { EvidencePanel } from './components/evidence/EvidencePanel';
import { ConsolePage } from './components/pages/ConsolePage';
import { GuardPage } from './components/pages/GuardPage';
import { ConfigModal } from './components/modals/ConfigModal';

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

  const { alerts, latestAlert, aiStatus, autoTrackStatus, trackDecision, trackOverlay } = useEventWebSocket();

  const autoTrack = useAutoTrack(autoTrackStatus, trackDecision);

  const sidebarLogEndRef = useRef<HTMLDivElement | null>(null);

  const {
    status: whepStatus,
    videoRef,
    videoLatencyMs,
    videoResolution,
    connect: connectWhep,
    disconnect: disconnectWhep,
  } = useWhepVideo();
  const { cam2WhepUrl } = useCameraSources();

  // 第二路摄像头 (PiP)
  const {
    status: whepStatus2,
    videoRef: videoRef2,
    connect: connectWhep2,
    disconnect: disconnectWhep2,
  } = useWhepVideo(cam2WhepUrl);
  // isCamSwapped: false = cam1主画面+cam2 PiP, true = cam2主画面+cam1 PiP
  const [isCamSwapped, setIsCamSwapped] = useState(false);
  // PiP 窗口状态
  const [isPipLarge, setIsPipLarge] = useState(false);  // false=240×135, true=480×270
  const [isPipHidden, setIsPipHidden] = useState(false); // 折叠到右下角图标

  const [showConfigPanel, setShowConfigPanel] = useState(false);
  const [activeTab, setActiveTab] = useState<SidebarTab>('console');
  const [isLogExpanded, setIsLogExpanded] = useState(false);
  const [isAiStatsExpanded, setIsAiStatsExpanded] = useState(false);
  const [isZoneDrawing, setIsZoneDrawing] = useState(false);

  const evidence = useEvidence();
  const { fetchEvidence } = evidence;
  const { isMissionRunning, toggleMission } = useMissionControl(addLog);
  const { isAudioPlaying, toggleAudio } = useAudioControl();
  const { guardStatus, toggleGuardMission, abortGuardMission } = useGuardMissionControl();
  const { isUiFullscreen, toggleFullscreen } = useFullscreenControl();

  const openNavPatrolPage = useCallback(() => {
    window.open('/nav-patrol.html', '_blank', 'noopener,noreferrer');
  }, []);

  const triggerSnapshot = useCallback(() => {
    addLog('手动拍照请求已发送', 'info', 'SNAPSHOT');
  }, [addLog]);

  // WebSocket 连接
  useEffect(() => { connectWs(); return () => { disconnectWs(); }; }, []);
  useEffect(() => { connectWhep(); return () => { disconnectWhep(); }; }, []);
  useEffect(() => { connectWhep2(); return () => { disconnectWhep2(); }; }, []);

  useEffect(() => {
    if (activeTab !== 'history') return;
    void fetchEvidence();
  }, [activeTab, fetchEvidence]);

  useVideoReconnectEffects({
    activeTab,
    connectWhep,
    disconnectWhep,
    connectWhep2,
    disconnectWhep2,
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
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        onOpenNavPatrolPage={openNavPatrolPage}
        onOpenConfig={() => setShowConfigPanel(true)}
        latestAlert={latestAlert}
        isUiFullscreen={isUiFullscreen}
      />

      {/* 主视图 */}
      <main className="flex-1 flex flex-col min-w-0 relative">
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
              videoRef2,
              isCamSwapped,
              onSwapCamera: () => setIsCamSwapped(v => !v),
              isPipLarge,
              onTogglePipSize: () => setIsPipLarge(v => !v),
              isPipHidden,
              onTogglePipHidden: () => setIsPipHidden(v => !v),
              isUiFullscreen,
              toggleFullscreen,
              trackOverlay,
              autoTrackEnabled: autoTrack.status?.enabled ?? false,
              guardEnabled: guardStatus?.enabled ?? false,
              isZoneDrawing,
              onToggleZoneDrawing: () => setIsZoneDrawing(v => !v),
              whepStatus,
              whepStatus2,
              currentWhep,
              videoLatencyMs,
              videoResolution,
              resolutionChip,
              telemetry,
              isConnected,
              aiStatus,
              autoTrackFrames: autoTrack.status?.frames_processed ?? 0,
              autoTrack,
              connectWs,
              connectWhep,
              connectWhep2,
              isMissionRunning,
              triggerSnapshot,
              toggleMission,
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
        ) : activeTab === 'admin' ? (
          /* 后台管理页面 */
          <div className="flex-1 flex flex-col bg-black overflow-hidden">
            <AdminPanel />
          </div>
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
