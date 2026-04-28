/**
 * BotDog Industrial Horizon - 重构版
 * 保留完整的前后端交互、WebSocket连接和WHEP视频流
 * 采用新布局：左侧导航 + 顶部状态栏 + 中央视频(HUD) + 右侧栏(日志+AI)
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useBotDogWebSocket } from './hooks/useBotDogWebSocket';
import { useWhepVideo } from './hooks/useWhepVideo';
import { ConfigPanel } from './components/ConfigPanel';
import { AdminPanel } from './components/AdminPanel';
import { useEventWebSocket } from './hooks/useEventWebSocket';
import { useAutoTrack } from './hooks/useAutoTrack';
import { GuardControlCenter } from './components/GuardControlCenter';
import { getApiUrl } from './config/api';
import { useEvidence } from './hooks/useEvidence';
import { useMissionControl } from './hooks/useMissionControl';
import { useAudioControl } from './hooks/useAudioControl';
import { useGuardMissionControl } from './hooks/useGuardMissionControl';
import { Sidebar, type SidebarTab } from './components/layout/Sidebar';
import { TopHeader } from './components/layout/TopHeader';
import { EvidencePanel } from './components/evidence/EvidencePanel';
import { VideoStage } from './components/video/VideoStage';
import { ConsoleRightPanel } from './components/console/ConsoleRightPanel';
import type { VideoSource } from './types/admin';

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

  const startupLoggedRef = useRef(false);
  const lastWsStatusRef = useRef<boolean | null>(null);
  const lastWhepStatusRef = useRef<string | null>(null);
  const wsDelayTimerRef = useRef<number | null>(null);
  const whepDelayTimerRef = useRef<number | null>(null);
  const sidebarLogEndRef = useRef<HTMLDivElement | null>(null);
  const tabSwitchRef = useRef(false);

  const {
    status: whepStatus,
    videoRef,
    videoLatencyMs,
    videoResolution,
    connect: connectWhep,
    disconnect: disconnectWhep,
  } = useWhepVideo();
  const connectWhepRef = useRef(connectWhep);

  // ── 动态摄像头 URL ──────────────────────────────────────────
  const [cam2WhepUrl, setCam2WhepUrl] = useState<string | undefined>(undefined);

  // 启动时从后端获取活跃视频源，动态设置 CAM2 的 WHEP URL
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(getApiUrl('/api/v1/video-sources/active'));
        if (!res.ok) return;
        const data = await res.json();
        const sources: VideoSource[] = data.sources || [];
        // CAM2 = 非主画面的第一个视频源
        const secondary = sources.find(s => !s.is_primary);
        if (secondary?.whep_url) {
          // 数据库里存的可能是 127.0.0.1，从浏览器访问时需替换为 OrangePi 的实际 IP
          const fixedUrl = secondary.whep_url.replace('127.0.0.1', window.location.hostname);
          setCam2WhepUrl(fixedUrl);
        }
      } catch (err) {
        console.error('获取视频源配置失败:', err);
      }
    })();
  }, []);

  // 第二路摄像头 (PiP)
  const {
    status: whepStatus2,
    videoRef: videoRef2,
    connect: connectWhep2,
    disconnect: disconnectWhep2,
  } = useWhepVideo(cam2WhepUrl);
  const connectWhep2Ref = useRef(connectWhep2);
  // isCamSwapped: false = cam1主画面+cam2 PiP, true = cam2主画面+cam1 PiP
  const [isCamSwapped, setIsCamSwapped] = useState(false);
  // PiP 窗口状态
  const [isPipLarge, setIsPipLarge] = useState(false);  // false=240×135, true=480×270
  const [isPipHidden, setIsPipHidden] = useState(false); // 折叠到右下角图标

  const [isUiFullscreen, setIsUiFullscreen] = useState(false);
  const [showConfigPanel, setShowConfigPanel] = useState(false);
  const [activeTab, setActiveTab] = useState<SidebarTab>('console');
  const [isLogExpanded, setIsLogExpanded] = useState(false);
  const [isAiStatsExpanded, setIsAiStatsExpanded] = useState(false);
  const [isZoneDrawing, setIsZoneDrawing] = useState(false);

  const fullscreenRequestedRef = useRef(false);
  const evidence = useEvidence();
  const { fetchEvidence } = evidence;
  const { isMissionRunning, toggleMission } = useMissionControl(addLog);
  const { isAudioPlaying, toggleAudio } = useAudioControl();
  const { guardStatus, toggleGuardMission, abortGuardMission } = useGuardMissionControl();

  const openNavPatrolPage = useCallback(() => {
    window.location.href = '/nav-patrol.html';
  }, []);

  const triggerSnapshot = useCallback(() => {
    addLog('手动拍照请求已发送', 'info', 'SNAPSHOT');
  }, [addLog]);

  // WebSocket 连接
  useEffect(() => { connectWs(); return () => { disconnectWs(); }; }, []);
  useEffect(() => { connectWhep(); return () => { disconnectWhep(); }; }, []);
  useEffect(() => { connectWhep2(); return () => { disconnectWhep2(); }; }, []);

  useEffect(() => {
    connectWhepRef.current = connectWhep;
  }, [connectWhep]);

  useEffect(() => {
    connectWhep2Ref.current = connectWhep2;
  }, [connectWhep2]);

  // ── App 内 tab 切换时的视频重连（cam1 + cam2）──
  useEffect(() => {
    if (activeTab === 'console' || activeTab === 'simulate' || activeTab === 'guard') {
      tabSwitchRef.current = true;
      const reconnectTimer = window.setTimeout(() => {
        connectWhepRef.current();
        connectWhep2Ref.current();
      }, 300);
      return () => window.clearTimeout(reconnectTimer);
    }
    tabSwitchRef.current = true;
    void disconnectWhep();
    void disconnectWhep2();
  }, [activeTab, disconnectWhep, disconnectWhep2]);

  // ── 浏览器标签切换恢复时重连（防止 WebRTC 被浏览器挂起）──
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible' &&
          (activeTab === 'console' || activeTab === 'simulate' || activeTab === 'guard')) {
        connectWhepRef.current();
        connectWhep2Ref.current();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, [activeTab]);

  useEffect(() => {
    if (activeTab !== 'history') return;
    void fetchEvidence();
  }, [activeTab, fetchEvidence]);

  useEffect(() => {
    if (startupLoggedRef.current) return;
    startupLoggedRef.current = true;
    addLog('系统启动检查开始', 'info', 'STARTUP');
  }, [addLog]);

  // WS 状态日志
  useEffect(() => {
    if (lastWsStatusRef.current === isConnected) return;
    lastWsStatusRef.current = isConnected;
    if (isConnected) {
      if (wsDelayTimerRef.current) { window.clearTimeout(wsDelayTimerRef.current); wsDelayTimerRef.current = null; }
      addLog('遥测链路已连接', 'info', 'WS');
      return;
    }
    if (wsDelayTimerRef.current) window.clearTimeout(wsDelayTimerRef.current);
    wsDelayTimerRef.current = window.setTimeout(() => {
      if (!isConnected) addLog('遥测链路未连接', 'error', 'WS');
      wsDelayTimerRef.current = null;
    }, 3000);
  }, [isConnected, addLog]);

  // WHEP 状态日志
  useEffect(() => {
    if (lastWhepStatusRef.current === whepStatus.status) return;
    lastWhepStatusRef.current = whepStatus.status;
    if (whepStatus.status === 'connected') {
      if (whepDelayTimerRef.current) { window.clearTimeout(whepDelayTimerRef.current); whepDelayTimerRef.current = null; }
      addLog('视频流连接成功', 'info', 'WHEP');
      return;
    }
    if (whepStatus.status === 'connecting') { addLog('视频流连接中', 'info', 'WHEP'); return; }
    if (whepDelayTimerRef.current) window.clearTimeout(whepDelayTimerRef.current);
    if (whepStatus.status === 'error') { addLog(`视频流连接失败: ${whepStatus.error || '未知错误'}`, 'error', 'WHEP'); return; }
    if (whepStatus.status === 'disconnected') {
      whepDelayTimerRef.current = window.setTimeout(() => {
        if (whepStatus.status === 'disconnected') addLog('视频流未连接', 'warning', 'WHEP');
        whepDelayTimerRef.current = null;
      }, 3000);
    }
  }, [whepStatus.status, whepStatus.error, addLog]);

  // 全屏
  const toggleFullscreen = () => {
    if (!isUiFullscreen) {
      const elem = document.documentElement;
      fullscreenRequestedRef.current = true;
      if (elem.requestFullscreen) elem.requestFullscreen().catch(console.error);
      else if ((elem as any).webkitRequestFullscreen) (elem as any).webkitRequestFullscreen();
    } else {
      fullscreenRequestedRef.current = false;
      if (document.exitFullscreen) document.exitFullscreen();
      else if ((document as any).webkitExitFullscreen) (document as any).webkitExitFullscreen();
    }
  };

  useEffect(() => {
    const handler = () => {
      const isFullscreen = !!(document.fullscreenElement || (document as any).webkitFullscreenElement);
      setIsUiFullscreen(isFullscreen);
      if (!isFullscreen && fullscreenRequestedRef.current) {
        fullscreenRequestedRef.current = false;
      }
    };
    document.addEventListener('fullscreenchange', handler);
    document.addEventListener('webkitfullscreenchange', handler);
    return () => {
      document.removeEventListener('fullscreenchange', handler);
      document.removeEventListener('webkitfullscreenchange', handler);
    };
  }, []);

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
          <div className="flex-1 flex min-h-0 relative">
            <VideoStage
              videoRef={videoRef}
              videoRef2={videoRef2}
              isCamSwapped={isCamSwapped}
              onSwapCamera={() => setIsCamSwapped(v => !v)}
              isPipLarge={isPipLarge}
              onTogglePipSize={() => setIsPipLarge(v => !v)}
              isPipHidden={isPipHidden}
              onTogglePipHidden={() => setIsPipHidden(v => !v)}
              isUiFullscreen={isUiFullscreen}
              toggleFullscreen={toggleFullscreen}
              trackOverlay={trackOverlay}
              autoTrackEnabled={autoTrack.status?.enabled ?? false}
              guardEnabled={guardStatus?.enabled ?? false}
              isZoneDrawing={isZoneDrawing}
              onToggleZoneDrawing={() => setIsZoneDrawing(v => !v)}
              whepStatus={whepStatus}
              whepStatus2={whepStatus2}
              currentWhep={currentWhep}
              videoLatencyMs={videoLatencyMs}
              videoResolution={videoResolution}
              resolutionChip={resolutionChip}
              telemetry={telemetry}
              isConnected={isConnected}
              aiStatus={aiStatus}
              autoTrackFrames={autoTrack.status?.frames_processed ?? 0}
              autoTrack={autoTrack}
              connectWs={connectWs}
              connectWhep={connectWhep}
              connectWhep2={connectWhep2}
              isMissionRunning={isMissionRunning}
              triggerSnapshot={triggerSnapshot}
              toggleMission={toggleMission}
            />

            {!isUiFullscreen && (
              <ConsoleRightPanel
                logs={logs}
                isLogExpanded={isLogExpanded}
                onToggleLogExpanded={() => setIsLogExpanded(!isLogExpanded)}
                sidebarLogEndRef={sidebarLogEndRef}
                systemStatus={systemStatus}
                isAudioPlaying={isAudioPlaying}
                toggleAudio={toggleAudio}
                aiStatus={aiStatus}
                isAiStatsExpanded={isAiStatsExpanded}
                onToggleAiStatsExpanded={() => setIsAiStatsExpanded(v => !v)}
                isMissionRunning={isMissionRunning}
                toggleMission={toggleMission}
                isConnected={isConnected}
                whepStatus={whepStatus}
                alerts={alerts}
                connectWs={connectWs}
                connectWhep={connectWhep}
              />
            )}
          </div>
        ) : activeTab === 'admin' ? (
          /* 后台管理页面 */
          <div className="flex-1 flex flex-col bg-black overflow-hidden">
            <AdminPanel />
          </div>
        ) : activeTab === 'guard' ? (
          <GuardControlCenter
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
      {showConfigPanel && (
        <div
          className="fixed inset-0 bg-black/85 flex items-center justify-center z-[1000] backdrop-blur-sm"
          onClick={(e) => { if (e.target === e.currentTarget) setShowConfigPanel(false); }}
        >
          <div className="w-[1000px] max-h-[90vh] rounded-none">
            <ConfigPanel onClose={() => setShowConfigPanel(false)} />
          </div>
        </div>
      )}
    </div>
  );
}
