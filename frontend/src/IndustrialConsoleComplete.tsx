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
import { ControlPad } from './components/ControlPad';
import { useEventWebSocket } from './hooks/useEventWebSocket';
import { useAutoTrack } from './hooks/useAutoTrack';
import { GuardControlCenter, GuardStatus } from './components/GuardControlCenter';
import { getApiUrl } from './config/api';
import { useEvidence } from './hooks/useEvidence';
import { Sidebar, type SidebarTab } from './components/layout/Sidebar';
import { TopHeader } from './components/layout/TopHeader';
import { EvidencePanel } from './components/evidence/EvidencePanel';
import { LogPanel } from './components/logs/LogPanel';
import { DetectionAlert } from './components/alerts/DetectionAlert';
import { VideoStage } from './components/video/VideoStage';
import type { VideoSource } from './types/admin';
import {
  Camera,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
  Volume2,
  VolumeX,
} from 'lucide-react';

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
  const [missionTaskId, setMissionTaskId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<SidebarTab>('console');
  const [isLogExpanded, setIsLogExpanded] = useState(false);
  const [isAiStatsExpanded, setIsAiStatsExpanded] = useState(false);
  const [isZoneDrawing, setIsZoneDrawing] = useState(false);
  const [guardStatus, setGuardStatus] = useState<GuardStatus | null>(null);
  const [isAudioPlaying, setIsAudioPlaying] = useState(false);

  const fullscreenRequestedRef = useRef(false);
  const evidence = useEvidence();
  const { fetchEvidence } = evidence;

  const openNavPatrolPage = useCallback(() => {
    window.location.href = '/nav-patrol.html';
  }, []);

  const isMissionRunning = missionTaskId !== null;

  const toggleMission = useCallback(async () => {
    try {
      if (missionTaskId) {
        // 停止巡检 → 立即禁用 AI 跟踪
        await fetch(getApiUrl('/api/v1/auto-track/disable'), { method: 'POST' })
          .catch(err => console.error('停用跟踪失败', err));
        await fetch(getApiUrl('/api/v1/session/stop'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_id: missionTaskId }),
        });
        setMissionTaskId(null);
        addLog('任务已停止，AI 跟踪已禁用', 'info', 'MISSION');
      } else {
        // 开始巡检 → 仅启动任务，AI 跟踪保持禁用，等用户手动点击「启用」
        const res = await fetch(getApiUrl('/api/v1/session/start'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_name: `巡检_${new Date().toLocaleTimeString([], { hour12: false })}` }),
        });
        const data = await res.json();
        setMissionTaskId(data.task_id);
        addLog(`任务已启动: ${data.task_name}`, 'info', 'MISSION');
      }
    } catch (err) {
      addLog(`任务操作失败: ${err}`, 'error', 'MISSION');
    }
  }, [missionTaskId, addLog]);

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

  // ── GuardStatus 轮询与操作 ──
  useEffect(() => {
    const fetchGuardStatus = async () => {
      try {
        const res = await fetch(getApiUrl('/api/v1/guard-mission/status'));
        if (res.ok) setGuardStatus(await res.json());
      } catch {}
    };
    fetchGuardStatus();
    const timer = setInterval(fetchGuardStatus, 1500);
    return () => clearInterval(timer);
  }, []);

  // ── 音频状态轮询 ──
  useEffect(() => {
    const fetchAudioStatus = async () => {
      try {
        const res = await fetch(getApiUrl('/api/v1/audio/status'));
        if (res.ok) {
          const data = await res.json();
          setIsAudioPlaying(data.playing);
        }
      } catch {}
    };
    fetchAudioStatus();
    const timer = setInterval(fetchAudioStatus, 2000);
    return () => clearInterval(timer);
  }, []);

  const toggleAudio = useCallback(async () => {
    try {
      const endpoint = isAudioPlaying ? '/api/v1/audio/stop' : '/api/v1/audio/play';
      const res = await fetch(getApiUrl(endpoint), { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setIsAudioPlaying(data.playing);
      }
    } catch (err) {
      console.error('切换音频失败:', err);
    }
  }, [isAudioPlaying]);

  const toggleGuardMission = useCallback(async () => {
    try {
      const endpoint = guardStatus?.enabled ? '/disable' : '/enable';
      await fetch(getApiUrl(`/api/v1/guard-mission${endpoint}`), { method: 'POST' });
    } catch (err) {
      console.error('切换自动驱离失败:', err);
    }
  }, [guardStatus?.enabled]);

  const abortGuardMission = useCallback(async () => {
    try {
      await fetch(getApiUrl('/api/v1/guard-mission/abort'), { method: 'POST' });
    } catch (err) {
      console.error('中止驱离失败:', err);
    }
  }, []);

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
          <>
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

            {/* 右侧栏 (日志 + AI 检测) */}
            {!isUiFullscreen && activeTab === 'console' && (
              <aside className="w-64 bg-black flex flex-col shadow-[-10px_0_30px_rgba(0,0,0,0.5)]">
                {/* 可折叠日志区 */}
                <LogPanel
                  logs={logs}
                  isExpanded={isLogExpanded}
                  onToggle={() => setIsLogExpanded(!isLogExpanded)}
                  sidebarLogEndRef={sidebarLogEndRef}
                />

                {/* 控制面板区 */}
                <div className="border-t border-white/20 bg-zinc-950 shrink-0">
                  <div className="px-3 py-2">
                    <ControlPad
                      isDisabled={systemStatus?.status === 'E_STOP_TRIGGERED'}
                      bottomCenterSlot={
                        <button
                          onClick={toggleAudio}
                          title={isAudioPlaying ? '停止音频' : '播放音频'}
                          className={`w-full h-full flex flex-col items-center justify-center gap-0.5 rounded border font-black text-[7px] uppercase tracking-tight transition-all duration-100 cursor-pointer select-none ${
                            isAudioPlaying
                              ? 'bg-amber-500/20 border-amber-500/60 text-amber-400 shadow-[0_0_6px_rgba(245,158,11,0.3)]'
                              : 'bg-zinc-800/80 text-white/60 border-white/15 hover:border-white/50 hover:text-white'
                          }`}
                        >
                          {isAudioPlaying
                            ? <Volume2 size={14} className="animate-pulse" />
                            : <VolumeX size={14} />}
                          <span>{isAudioPlaying ? '音频' : '音频'}</span>
                        </button>
                      }
                    />
                  </div>
                </div>

                {/* AI 检测区 */}
                <div className="flex-1 flex flex-col overflow-hidden">
                  <div className="p-4 border-b border-white/20 flex items-center justify-between bg-black shrink-0">
                    <div className="flex items-center space-x-3 font-black text-white">
                      <Camera size={16} />
                      <span className="text-[11px] uppercase tracking-widest">AI 识别</span>
                    </div>
                    {aiStatus && (
                      <span className={`text-[9px] px-2 py-0.5 font-black rounded uppercase tracking-tighter ${
                        aiStatus.mode === 'alert' ? 'bg-red-600 text-white' :
                        aiStatus.mode === 'suspect' ? 'bg-amber-500 text-black' :
                        aiStatus.mode === 'patrol' ? 'bg-blue-500 text-white' :
                        'bg-white text-black'
                      }`}>
                        {{ idle: '待机', patrol: '巡逻', suspect: '疑似', alert: '告警' }[aiStatus.mode] || aiStatus.mode}
                      </span>
                    )}
                  </div>
                  {/* AI 统计，可折叠，默认收起 */}
                  <div
                    className="px-4 py-2 border-b border-white/10 bg-black/80 flex items-center justify-between cursor-pointer hover:bg-white/5 transition-all"
                    onClick={() => setIsAiStatsExpanded(v => !v)}
                  >
                    <span className="text-[9px] font-black uppercase tracking-widest text-white/40">统计数据</span>
                    {isAiStatsExpanded ? <ChevronDown size={12} className="text-white/40" /> : <ChevronUp size={12} className="text-white/40" />}
                  </div>
                  {isAiStatsExpanded && (
                    <div className="px-4 py-3 border-b border-white/10 bg-black/80">
                      <div className="grid grid-cols-2 gap-3 text-[10px] font-mono text-white/80">
                        <div className="flex items-center justify-between">
                          <span className="text-white/50">处理帧</span>
                          <span>{aiStatus ? aiStatus.frames_processed : '--'}</span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-white/50">检测数</span>
                          <span>{aiStatus ? aiStatus.detections_count : '--'}</span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-white/50">命中</span>
                          <span>{aiStatus ? aiStatus.hits : '--'}</span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-white/50">稳定阈值</span>
                          <span>{aiStatus ? aiStatus.stable_hits : '--'}</span>
                        </div>
                      </div>
                    </div>
                  )}
                  <div className="px-4 py-3 border-b border-white/10 bg-black/60 flex items-center justify-between">
                    <div className="text-[10px] font-black uppercase tracking-widest text-white/70">
                      任务控制
                    </div>
                    <button
                      onClick={toggleMission}
                      disabled={!isConnected}
                      className={`px-3 py-1 text-[9px] font-black uppercase tracking-widest rounded border transition-all disabled:opacity-40 disabled:cursor-not-allowed ${
                        isMissionRunning
                          ? 'border-white text-white hover:bg-white hover:text-black'
                          : 'border-white/40 text-white/70 hover:border-white hover:text-white'
                      }`}
                    >
                      {isMissionRunning ? '终止任务' : '开始巡检'}
                    </button>
                  </div>
                  <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar bg-zinc-900/20">
                    {alerts.length === 0 ? (
                      <div className="h-full flex flex-col items-center justify-center text-slate-500 space-y-3">
                        <ShieldCheck size={40} className="text-white/20" />
                        <p className="text-[10px] uppercase font-black tracking-widest text-white/30">监测运行中...</p>
                        {(whepStatus.status !== 'connected' || !isConnected) && (
                          <button
                            onClick={() => {
                              if (!isConnected) connectWs();
                              connectWhep();
                            }}
                            className="mt-2 px-3 py-1.5 text-[9px] font-black uppercase tracking-widest border border-white/20 text-white/80 hover:text-white hover:border-white/60 transition-all"
                          >
                            重连所有链路
                          </button>
                        )}
                      </div>
                    ) : (
                      alerts.slice(0, 15).map((a, i) => (
                        <DetectionAlert key={`${a.timestamp}-${i}`} data={a} />
                      ))
                    )}
                  </div>
                </div>
              </aside>
            )}
          </>
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
