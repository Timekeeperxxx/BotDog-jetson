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
import { AutoTrackPanel } from './components/AutoTrackPanel';
import { TrackOverlay } from './components/TrackOverlay1';
import { GuardControlCenter, GuardStatus } from './components/GuardControlCenter';
import { ZoneDrawer } from './components/ZoneDrawer';
import { getApiUrl } from './config/api';
import { useEvidence } from './hooks/useEvidence';
import { Sidebar, type SidebarTab } from './components/layout/Sidebar';
import { TopHeader } from './components/layout/TopHeader';
import { EvidencePanel } from './components/evidence/EvidencePanel';
import { LogPanel } from './components/logs/LogPanel';
import { DetectionAlert } from './components/alerts/DetectionAlert';
import { StatusWidgets } from './components/status/StatusWidgets';
import type { VideoSource } from './types/admin';
import {
  Camera,
  Play,
  Square,
  Maximize2,
  Minimize2,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
  ArrowLeftRight,
  X,
  PenLine,
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
          <div className="flex-1 flex min-h-0 relative">
            {/* 视频监控区 */}
            <div className={`flex-1 bg-black relative overflow-hidden transition-all duration-300 ${isUiFullscreen ? 'fixed inset-0 z-[100]' : 'border-r border-white/20'}`}>
              {/* CAM1 video - single element, CSS determines main vs PiP position */}
              <video
                ref={videoRef}
                autoPlay playsInline muted
                className="absolute object-cover bg-black transition-all duration-300"
                style={isCamSwapped ? {
                  bottom: '108px', right: '16px', top: 'auto', left: 'auto',
                  width: isPipLarge ? '480px' : '270px',
                  height: isPipLarge ? '270px' : '152px',
                  zIndex: 21, borderRadius: '8px',
                  display: isPipHidden ? 'none' : undefined,
                } : {
                  inset: 0, width: '100%', height: '100%', zIndex: 1, borderRadius: 0,
                }}
              />
              {/* YOLO 检测框 + 决策区域叠层（跟随 AI 跟踪或驱离启用状态） */}
              {!isCamSwapped && trackOverlay && (autoTrack.status?.enabled || guardStatus?.enabled) && (
                <TrackOverlay data={trackOverlay} videoRef={videoRef} />
              )}
              {/* 禁区绘制叠层（始终挂载，active 控制交互） */}
              <ZoneDrawer
                frameW={trackOverlay?.frame_w ?? 1280}
                frameH={trackOverlay?.frame_h ?? 720}
                active={isZoneDrawing}
                onClose={() => setIsZoneDrawing(false)}
              />
              {/* CAM2 video - single element */}
              <video
                ref={videoRef2}
                autoPlay playsInline muted
                className="absolute object-cover bg-black transition-all duration-300"
                style={isCamSwapped ? {
                  inset: 0, width: '100%', height: '100%', zIndex: 1, borderRadius: 0,
                } : {
                  bottom: '108px', right: '16px', top: 'auto', left: 'auto',
                  width: isPipLarge ? '480px' : '240px',
                  height: isPipLarge ? '270px' : '135px',
                  zIndex: 21, borderRadius: '8px',
                  display: isPipHidden ? 'none' : undefined,
                }}
              />

              {/* Main area disconnect overlay */}
              {(() => {
                const mainStatus = isCamSwapped ? whepStatus2 : whepStatus;
                const mainConnect = isCamSwapped ? connectWhep2 : connectWhep;
                if (mainStatus.status === 'connected') return null;
                return (
                  <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-900/88 z-5">
                    <div className="text-5xl mb-4 opacity-50">
                      {mainStatus.status === 'connecting' ? (
                        <div className="w-12 h-12 rounded-full border-4 border-slate-200/20 border-t-slate-200 mx-auto" style={{ animation: 'videoSpin 1s linear infinite' }} />
                      ) : mainStatus.status === 'error' ? (
                        <span className="text-red-400 font-bold">x</span>
                      ) : (
                        <Camera size={48} className="text-white/30" />
                      )}
                    </div>
                    <div className="text-lg font-bold text-slate-200 mb-2">视频流 {mainStatus.status === 'connecting' ? '连接中...' : mainStatus.error || '未连接'}</div>
                    {mainStatus.error && (
                      <div className="text-sm text-red-500 mb-4 px-4 py-2 bg-red-500/10 rounded">{mainStatus.error}</div>
                    )}
                    <div className="text-xs text-slate-500">{isConnected ? '等待WHEP连接...' : '等待后端连接...'}</div>
                    <button onClick={mainConnect} className="mt-4 px-4 py-2 text-[10px] font-black uppercase tracking-widest border border-white/20 text-white/80 hover:text-white hover:border-white/60 transition-all">重新连接</button>
                  </div>
                );
              })()}


              {/* HUD 叠加 */}
              {activeTab === 'console' && (
                <div className="absolute inset-0 pointer-events-none p-6">
                  <div className="h-full flex flex-col justify-between items-center relative">
                    <div className="w-full flex justify-between">
                      <div className="w-6 h-6 border-t-2 border-l-2 border-white/40" />
                      <div className="w-6 h-6 border-t-2 border-r-2 border-white/40" />
                    </div>
                    <div className="w-40 h-40 border border-white/20 rounded-full flex items-center justify-center">
                      <div className="w-8 h-[1px] bg-white/50" />
                      <div className="w-[1px] h-8 bg-white/50 absolute" />
                    </div>
                    <div className="w-full flex justify-between">
                      <div className="w-6 h-6 border-b-2 border-l-2 border-white/40" />
                      <div className="w-6 h-6 border-b-2 border-r-2 border-white/40" />
                    </div>
                  </div>
                </div>
              )}

              <StatusWidgets
                resolutionChip={resolutionChip}
                whepStatusText={currentWhep.text}
                whepStatusColor={currentWhep.color}
                telemetry={telemetry}
                isUiFullscreen={isUiFullscreen}
                aiStatus={aiStatus}
                autoTrackFrames={autoTrack.status?.frames_processed ?? 0}
              />

              {activeTab === 'console' && !isUiFullscreen && (
                <div className="absolute top-4 right-4 z-10 flex flex-col gap-2">
                  <div className="bg-black/40 border border-white/10 px-3 py-2 text-[10px] font-mono text-white/80">
                    <div className="uppercase tracking-widest text-white/40 mb-1">WHEP</div>
                    <div className="flex items-center gap-2">
                      <span className={`font-black ${currentWhep.color}`}>{currentWhep.text}</span>
                      {whepStatus.status !== 'connected' && (
                        <button
                          onClick={connectWhep}
                          className="text-[9px] font-black uppercase tracking-widest border border-white/20 text-white/70 px-2 py-0.5 hover:text-white hover:border-white/60 transition-all"
                        >
                          重连
                        </button>
                      )}
                    </div>
                    <div className="mt-1 text-white/50">延迟: {videoLatencyMs !== null ? `${videoLatencyMs}ms` : '--'}</div>
                  </div>
                  {/* 自动跟踪控制面板 */}
                  <div className="pointer-events-auto">
                    <AutoTrackPanel {...autoTrack} isMissionRunning={isMissionRunning} />
                  </div>

                  <div className="bg-black/40 border border-white/10 px-3 py-2 text-[10px] font-mono text-white/80">
                    <div className="uppercase tracking-widest text-white/40 mb-1">系统状态</div>
                    <div className="flex items-center gap-2">
                      <span className={`font-black ${isConnected ? 'text-emerald-400' : 'text-red-400'}`}>{isConnected ? '链路在线' : '链路离线'}</span>
                      {!isConnected && (
                        <span className="text-[9px] uppercase tracking-widest text-red-300">检查后端</span>
                      )}
                    </div>
                    {!isConnected && (
                      <button
                        onClick={connectWs}
                        className="mt-2 text-[9px] font-black uppercase tracking-widest border border-white/20 text-white/70 px-2 py-0.5 hover:text-white hover:border-white/60 transition-all"
                      >
                        重新连接
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* PiP overlay: border, badges, masks, controls */}
              {activeTab === 'console' && !isUiFullscreen && (() => {
                const pipStatus = isCamSwapped ? whepStatus : whepStatus2;
                const pipLabel = isCamSwapped ? 'CAM1' : 'CAM2';
                const pipW = isPipLarge ? 480 : 240;
                const pipH = isPipLarge ? 270 : 135;

                // Collapsed state: show a small restore button
                if (isPipHidden) {
                  return (
                    <div
                      className="absolute z-30 flex items-center justify-center cursor-pointer group/pip-restore"
                      style={{ bottom: '108px', right: '16px', width: '48px', height: '48px' }}
                      onClick={() => setIsPipHidden(false)}
                      title="恢复画中画"
                    >
                      <div className="w-full h-full rounded-xl bg-black/80 border-2 border-white/20 group-hover/pip-restore:border-white/60 flex items-center justify-center transition-all shadow-lg">
                        <Camera size={20} className="text-white/60 group-hover/pip-restore:text-white transition-colors" />
                      </div>
                      <div className={`absolute top-1 right-1 w-2 h-2 rounded-full ${
                        pipStatus.status === 'connected' ? 'bg-emerald-500' :
                        pipStatus.status === 'connecting' ? 'bg-amber-500 animate-pulse' : 'bg-red-500'
                      }`} />
                    </div>
                  );
                }

                return (
                  <div
                    className="absolute z-30 cursor-pointer group/pip transition-all duration-300"
                    style={{ bottom: '108px', right: '16px', width: `${pipW}px`, height: `${pipH}px` }}
                    onClick={() => setIsPipLarge(v => !v)}
                    title={isPipLarge ? '缩小画中画' : '放大画中画'}
                  >
                    {/* visible border */}
                    <div className="absolute inset-0 rounded-lg border-2 border-white/25 group-hover/pip:border-white/60 shadow-[0_4px_30px_rgba(0,0,0,0.8)] transition-colors pointer-events-none" />

                    {/* status badge (top-left) */}
                    <div className="absolute top-1.5 left-1.5 flex items-center space-x-1.5 bg-black/65 px-2 py-0.5 rounded text-[8px] font-mono font-black uppercase tracking-wider pointer-events-none">
                      <div className={`w-1.5 h-1.5 rounded-full ${
                        pipStatus.status === 'connected' ? 'bg-emerald-500' :
                        pipStatus.status === 'connecting' ? 'bg-amber-500 animate-pulse' : 'bg-red-500'
                      }`} />
                      <span className="text-white/75">{pipLabel}</span>
                    </div>

                    {/* hide button (top-right) */}
                    <button
                      className="absolute top-1.5 right-1.5 w-5 h-5 flex items-center justify-center bg-black/60 hover:bg-white/20 rounded transition-colors z-10"
                      onClick={(e) => { e.stopPropagation(); setIsPipHidden(true); }}
                      title="隐藏画中画"
                    >
                      <X size={10} className="text-white/75" />
                    </button>

                    {/* size indicator (center-bottom, on hover) */}
                    <div className="absolute bottom-1.5 left-1/2 -translate-x-1/2 opacity-0 group-hover/pip:opacity-100 transition-opacity bg-black/60 px-1.5 py-0.5 rounded pointer-events-none">
                      <span className="text-[8px] font-mono text-white/60">{isPipLarge ? '480×270' : '240×135'}</span>
                    </div>

                    {/* swap button (bottom-right) */}
                    <button
                      className="absolute bottom-1.5 right-1.5 w-5 h-5 flex items-center justify-center bg-black/60 hover:bg-white/20 rounded transition-colors z-10"
                      onClick={(e) => { e.stopPropagation(); setIsCamSwapped(v => !v); }}
                      title="互换主画面与画中画"
                    >
                      <ArrowLeftRight size={10} className="text-white/75" />
                    </button>

                    {/* disconnect mask */}
                    {pipStatus.status !== 'connected' && (
                      <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/70 rounded-lg pointer-events-none">
                        {pipStatus.status === 'connecting' ? (
                          <div className="w-6 h-6 rounded-full border-2 border-white/20 border-t-white" style={{ animation: 'videoSpin 1s linear infinite' }} />
                        ) : <Camera size={20} className="text-white/30" />}
                        <span className="text-[9px] mt-1.5 font-bold text-white/40">
                          {pipStatus.status === 'connecting' ? '连接中' : pipStatus.error || '未连接'}
                        </span>
                      </div>
                    )}
                  </div>
                );
              })()}



              {/* 底部浮动控制栏 */}
              {(activeTab === 'console' || activeTab === 'simulate') && (
                <div className="absolute bottom-8 left-1/2 -translate-x-1/2 w-full max-w-lg px-6 z-30 pointer-events-auto">
                  <div className="bg-black border-2 border-white/30 p-3 rounded-xl shadow-[0_20px_50px_rgba(0,0,0,1)] flex items-center justify-between px-8">
                  <div className="flex items-center space-x-5 text-white">
                    <button onClick={toggleFullscreen} className="p-2 hover:bg-white hover:text-black rounded-lg transition-all" title={isUiFullscreen ? '退出全屏' : '全屏'}>
                      {isUiFullscreen ? <Minimize2 size={22} /> : <Maximize2 size={22} />}
                    </button>
                    <div className="h-8 w-px bg-white/30" />
                    <button onClick={triggerSnapshot} className="p-2 hover:bg-white hover:text-black rounded-lg transition-all" title="拍照">
                      <Camera size={22} />
                    </button>
                    <div className="h-8 w-px bg-white/30" />
                    <button
                      onClick={() => setIsZoneDrawing(v => !v)}
                      className={`p-2 rounded-lg transition-all ${
                        isZoneDrawing
                          ? 'bg-green-500 text-black'
                          : 'hover:bg-white hover:text-black text-white'
                      }`}
                      title={isZoneDrawing ? '退出画禁区模式' : '画禁区'}
                    >
                      <PenLine size={22} />
                    </button>
                  </div>
                  <div className="flex items-center space-x-3">
                    <span className={`text-[10px] font-black uppercase tracking-widest px-3 py-2 rounded border ${
                      isMissionRunning
                        ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                        : 'bg-white/5 text-slate-400 border-white/10'
                    }`}>
                      {isMissionRunning ? '巡检中' : '待命'}
                    </span>
                    <button
                      onClick={toggleMission}
                      disabled={!isConnected}
                      className={`flex items-center space-x-4 px-12 py-3 rounded-lg font-black text-xs uppercase transition-all transform active:scale-95 shadow-xl disabled:opacity-40 disabled:cursor-not-allowed ${
                        isMissionRunning
                          ? 'bg-white text-black border-2 border-white'
                          : 'bg-white text-black ring-4 ring-white/20'
                      }`}
                    >
                      {isMissionRunning ? <><Square size={14} fill="black" /><span>终止任务</span></> : <><Play size={14} fill="black" /><span>开始巡检</span></>}
                    </button>
                  </div>
                </div>
              </div>
              )}
            </div>

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
