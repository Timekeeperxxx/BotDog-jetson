/**
 * BotDog Industrial Horizon - 重构版
 * 保留完整的前后端交互、WebSocket连接和WHEP视频流
 * 采用新布局：左侧导航 + 顶部状态栏 + 中央视频(HUD) + 右侧栏(日志+AI)
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useBotDogWebSocket } from './hooks/useBotDogWebSocket';
import { useWhepVideo } from './hooks/useWhepVideo';
import { ConfigPanel } from './components/ConfigPanel';
import { useEventWebSocket } from './hooks/useEventWebSocket';
import { getApiUrl } from './config/api';
import {
  Activity,
  Battery,
  Wifi,
  Camera,
  Thermometer,
  LayoutGrid,
  History,
  Bell,
  Info,
  Terminal,
  ChevronDown,
  ChevronUp,
  Play,
  Square,
  Maximize2,
  Minimize2,
  ShieldCheck,
  Settings,
  Search,
  Download,
  Clock,
  MapPin,
  Trash2,
} from 'lucide-react';

interface EvidenceItem {
  evidence_id: number;
  task_id: number;
  event_type: string;
  event_code?: string | null;
  severity: 'INFO' | 'WARNING' | 'CRITICAL';
  message?: string | null;
  confidence?: number | null;
  file_path: string;
  image_url?: string | null;
  gps_lat?: number | null;
  gps_lon?: number | null;
  created_at: string;
}

// ==================== 侧边导航按钮 ====================
function SidebarBtn({ icon, active, onClick, label, dot }: {
  icon: React.ReactNode;
  active: boolean;
  onClick?: () => void;
  label: string;
  dot?: boolean;
}) {
  return (
    <div
      onClick={onClick}
      className={`relative p-3 rounded-lg cursor-pointer transition-all duration-200 group ${
        active
          ? 'bg-white text-black shadow-[0_0_20px_rgba(255,255,255,0.3)]'
          : 'text-slate-400 hover:text-white hover:bg-zinc-900'
      }`}
    >
      {icon}
      {dot && <div className="absolute top-2 right-2 w-2 h-2 bg-red-600 rounded-full border-2 border-black" />}
      <div className="absolute left-16 opacity-0 group-hover:opacity-100 pointer-events-none bg-white text-black border-2 border-white px-3 py-1.5 rounded text-[10px] uppercase font-black whitespace-nowrap transition-all transform group-hover:translate-x-1 z-[100]">
        {label}
      </div>
    </div>
  );
}

// ==================== 顶部状态指标 ====================
function TopStatus({ icon, value, label }: { icon: React.ReactNode; value: string; label: string }) {
  return (
    <div className="flex items-center space-x-3">
      <div className="p-2 rounded-sm bg-zinc-900 text-white border border-white/10">
        {icon}
      </div>
      <div className="flex flex-col -space-y-1">
        <span className="text-[9px] uppercase font-black text-slate-500 tracking-tighter">{label}</span>
        <span className="text-[11px] font-mono font-black text-white">{value}</span>
      </div>
    </div>
  );
}

// ==================== 顶部数据点 ====================
function DataPointHeader({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div className="flex items-baseline space-x-2 group">
      <span className="text-[9px] uppercase font-black text-slate-500 tracking-tighter group-hover:text-white">{label}</span>
      <span className="text-lg font-mono font-black text-white">{value}</span>
      <span className="text-[10px] font-mono font-bold text-slate-400">{unit}</span>
    </div>
  );
}

// ==================== AI 检测卡片 ====================
function getImageUrl(imageUrl?: string | null): string | null {
  if (!imageUrl) return null;
  if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) {
    return imageUrl;
  }
  return getApiUrl(imageUrl);
}

function DetectionAlert({ data }: {
  data: { severity: string; message: string; confidence?: number; timestamp: string; image_url?: string };
}) {
  const isStranger = data.severity === 'CRITICAL';
  const imageSrc = getImageUrl(data.image_url);
  return (
    <div className="group bg-zinc-900 border-2 border-white/10 p-3 rounded-xl shadow-2xl hover:border-white transition-all cursor-pointer">
      <div className="flex items-center justify-between mb-3 border-b border-white/5 pb-2">
        <div className="flex items-center space-x-2">
          <div className={`w-2 h-2 rounded-full ${isStranger ? 'bg-red-500 animate-pulse' : 'bg-orange-500'}`} />
          <span className="text-[10px] font-black uppercase tracking-widest text-white">
            {data.severity}
          </span>
        </div>
        <span className="text-[10px] font-mono font-black text-slate-400">
          {new Date(data.timestamp).toLocaleTimeString('zh-CN', { hour12: false }).split(':').slice(1).join(':')}
        </span>
      </div>
      <div className="flex space-x-4 items-center">
        {imageSrc && (
          <div className="w-14 h-14 rounded-lg overflow-hidden border-2 border-white/20 bg-black shadow-inner shrink-0">
            <img src={imageSrc} className="w-full h-full object-cover opacity-90 group-hover:scale-110 transition-transform" />
          </div>
        )}
        <div className="flex-1 min-w-0">
          <p className="text-[12px] font-black text-white truncate leading-tight tracking-wide">{data.message}</p>
          {data.confidence !== undefined && (
            <div className="flex items-center space-x-2 mt-2">
              <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden border border-white/5">
                <div className="h-full bg-white" style={{ width: `${data.confidence * 100}%` }} />
              </div>
              <p className="text-[10px] text-white font-mono font-black">{(data.confidence * 100).toFixed(0)}%</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
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

  const { alerts, latestAlert, aiStatus } = useEventWebSocket();

  const startupLoggedRef = useRef(false);
  const lastWsStatusRef = useRef<boolean | null>(null);
  const lastWhepStatusRef = useRef<string | null>(null);
  const wsDelayTimerRef = useRef<number | null>(null);
  const whepDelayTimerRef = useRef<number | null>(null);
  const sidebarLogEndRef = useRef<HTMLDivElement | null>(null);
  const tabSwitchRef = useRef(false);

  const { status: whepStatus, videoRef, videoLatencyMs, connect: connectWhep, disconnect: disconnectWhep } = useWhepVideo();
  const connectWhepRef = useRef(connectWhep);

  const [isUiFullscreen, setIsUiFullscreen] = useState(false);
  const [showConfigPanel, setShowConfigPanel] = useState(false);
  const [missionTaskId, setMissionTaskId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<'console' | 'history'>('console');
  const [isLogExpanded, setIsLogExpanded] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<Set<number>>(new Set());
  const [evidenceDeleting, setEvidenceDeleting] = useState(false);

  const fullscreenRequestedRef = useRef(false);

  const isMissionRunning = systemStatus.status === 'IN_MISSION';

  const toggleMission = useCallback(async () => {
    try {
      if (missionTaskId) {
        await fetch(getApiUrl('/api/v1/session/stop'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_id: missionTaskId }),
        });
        setMissionTaskId(null);
        addLog('任务已停止', 'info', 'MISSION');
      } else {
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

  const fetchEvidence = useCallback(async () => {
    setEvidenceLoading(true);
    setEvidenceError(null);
    try {
      const res = await fetch(getApiUrl('/api/v1/evidence'));
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      setEvidenceItems(data.items || []);
      setSelectedEvidence(new Set());
    } catch (err) {
      setEvidenceError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setEvidenceLoading(false);
    }
  }, []);

  const deleteEvidenceByIds = useCallback(async (ids: number[]) => {
    if (ids.length === 0) return;
    setEvidenceDeleting(true);
    setEvidenceError(null);
    try {
      const res = await fetch(getApiUrl('/api/v1/evidence/bulk-delete'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ evidence_ids: ids }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      if (!data.success) {
        throw new Error('删除失败');
      }
      await fetchEvidence();
    } catch (err) {
      setEvidenceError(err instanceof Error ? err.message : '删除失败');
    } finally {
      setEvidenceDeleting(false);
    }
  }, [fetchEvidence]);

  const deleteEvidenceSingle = useCallback((id: number) => {
    void deleteEvidenceByIds([id]);
  }, [deleteEvidenceByIds]);

  const deleteEvidenceSelected = useCallback(() => {
    void deleteEvidenceByIds(Array.from(selectedEvidence));
  }, [deleteEvidenceByIds, selectedEvidence]);

  // WebSocket 连接
  useEffect(() => { connectWs(); return () => { disconnectWs(); }; }, []);
  useEffect(() => { connectWhep(); return () => { disconnectWhep(); }; }, []);

  useEffect(() => {
    connectWhepRef.current = connectWhep;
  }, [connectWhep]);

  useEffect(() => {
    if (activeTab === 'console') {
      tabSwitchRef.current = true;
      const reconnectTimer = window.setTimeout(() => {
        connectWhepRef.current();
      }, 300);
      return () => window.clearTimeout(reconnectTimer);
    }
    tabSwitchRef.current = true;
    void disconnectWhep();
  }, [activeTab, disconnectWhep]);

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

  // 自动滚动日志
  useEffect(() => {
    if (isLogExpanded) sidebarLogEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs, isLogExpanded]);

  const logRecentStatus = useMemo(() => logs.slice(-5).map(l => l.level), [logs]);

  const resolutionWidth = Number(import.meta.env.VITE_STREAM_WIDTH || 1920);
  const resolutionChip = resolutionWidth === 1280 ? '720p' : '1080p';

  const whepConfig: Record<string, { color: string; text: string }> = {
    disconnected: { color: 'text-red-500', text: '未连接' },
    connecting: { color: 'text-amber-500', text: '连接中...' },
    connected: { color: 'text-emerald-500', text: '已连接' },
    error: { color: 'text-red-500', text: whepStatus.error || '错误' },
  };
  const currentWhep = whepConfig[whepStatus.status] || whepConfig.disconnected;

  const filteredAlerts = useMemo(() => {
    if (!searchQuery) return alerts;
    return alerts.filter(a => a.message.includes(searchQuery) || a.severity.includes(searchQuery));
  }, [alerts, searchQuery]);

  const filteredEvidence = useMemo(() => {
    if (!searchQuery) return evidenceItems;
    return evidenceItems.filter(item => (item.message || '').includes(searchQuery) || item.severity.includes(searchQuery));
  }, [evidenceItems, searchQuery]);

  const toggleEvidenceSelected = (id: number) => {
    setSelectedEvidence((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleAllEvidence = () => {
    if (filteredEvidence.length === 0) return;
    const allSelected = filteredEvidence.every((item) => selectedEvidence.has(item.evidence_id));
    if (allSelected) {
      setSelectedEvidence(new Set());
      return;
    }
    const next = new Set<number>();
    filteredEvidence.forEach((item) => next.add(item.evidence_id));
    setSelectedEvidence(next);
  };

  return (
    <div className="flex h-screen w-full bg-[#050506] text-white font-sans overflow-hidden antialiased selection:bg-white selection:text-black">

      {/* 侧边导航 */}
      {!isUiFullscreen && (
        <nav className="w-14 flex flex-col items-center py-6 bg-black border-r border-white/20 z-50 shadow-2xl">
          <div className="w-9 h-9 border-2 border-white rounded-sm flex items-center justify-center mb-10 group cursor-pointer hover:bg-white transition-all">
            <Activity size={18} className="text-white group-hover:text-black" />
          </div>
          <div className="flex-1 flex flex-col space-y-5">
            <SidebarBtn icon={<LayoutGrid size={20} />} active={activeTab === 'console'} onClick={() => setActiveTab('console')} label="控制台" />
            <SidebarBtn icon={<History size={20} />} active={activeTab === 'history'} onClick={() => setActiveTab('history')} label="档案库" />
          </div>
          <div className="mt-auto space-y-5 pt-4 border-t border-white/10">
            <SidebarBtn icon={<Settings size={20} />} active={false} onClick={() => setShowConfigPanel(true)} label="设置" />
            <SidebarBtn icon={<Bell size={20} />} active={false} dot={!!latestAlert} label="告警" />
          </div>
        </nav>
      )}

      {/* 主视图 */}
      <main className="flex-1 flex flex-col min-w-0 relative">

        {/* 顶部页眉 */}
        {!isUiFullscreen && (
          <header className="h-12 bg-black backdrop-blur-md border-b border-white/20 flex items-center justify-between px-6 z-40">
            <div className="flex items-center space-x-6">
              <div className="flex items-center space-x-3">
                <span className="text-[11px] font-black text-white uppercase tracking-widest">BotDog</span>
                <div className="h-4 w-px bg-white/30" />
                <span className="text-[10px] font-mono text-slate-300 font-bold tracking-tight">V5.0-核心终端</span>
              </div>
              {isMissionRunning && (
                <div className="flex items-center space-x-2 px-2.5 py-1 bg-white rounded-sm border border-white shadow-[0_0_10px_rgba(255,255,255,0.2)]">
                  <div className="w-1.5 h-1.5 bg-black rounded-full animate-pulse" />
                  <span className="text-[9px] font-black text-black uppercase tracking-tighter">Active</span>
                </div>
              )}
            </div>
            <div className="flex items-center space-x-10">
              <div className="hidden lg:flex items-center space-x-8 pr-8 border-r border-white/20 font-bold">
                <DataPointHeader label="速度" value={telemetry ? telemetry.position.groundspeed.toFixed(1) : '--'} unit="m/s" />
                <DataPointHeader label="航向" value={telemetry ? (telemetry.attitude.yaw || 0).toFixed(0) : '--'} unit="°" />
                <DataPointHeader label="延迟" value={videoLatencyMs !== null ? `${videoLatencyMs}` : '--'} unit="ms" />
              </div>
              <div className="flex items-center space-x-6">
                <TopStatus icon={<Wifi size={16} />} value={isConnected ? '在线' : '离线'} label="链路" />
                <TopStatus icon={<Battery size={16} />} value={telemetry ? `${telemetry.battery_pct.toFixed(0)}%` : '--'} label="电量" />
                <TopStatus icon={<Thermometer size={16} />} value={telemetry ? `${telemetry.core_temp_c.toFixed(0)}°C` : '--'} label="温度" />
              </div>
              <div className="text-[11px] font-mono font-black text-white pl-6 border-l border-white/20">
                {new Date().toLocaleTimeString('zh-CN', { hour12: false })}
              </div>
            </div>
          </header>
        )}

        {activeTab === 'console' ? (
          <div className="flex-1 flex min-h-0 relative">
            {/* 视频监控区 */}
            <div className={`flex-1 bg-black relative overflow-hidden transition-all duration-300 ${isUiFullscreen ? 'fixed inset-0 z-[100]' : 'border-r border-white/20'}`}>
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="w-full h-full object-cover bg-black"
              />

              {/* 视频未连接遮罩 */}
              {whepStatus.status !== 'connected' && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-900/88 z-5">
                  <div className="text-5xl mb-4 opacity-50">
                    {whepStatus.status === 'connecting' ? (
                      <div className="w-12 h-12 rounded-full border-4 border-slate-200/20 border-t-slate-200 mx-auto" style={{ animation: 'videoSpin 1s linear infinite' }} />
                    ) : whepStatus.status === 'error' ? (
                      <span className="text-red-400 font-bold">x</span>
                    ) : (
                      <Camera size={48} className="text-white/30" />
                    )}
                  </div>
                  <div className="text-lg font-bold text-slate-200 mb-2">视频流 {currentWhep.text}</div>
                  {whepStatus.error && (
                    <div className="text-sm text-red-500 mb-4 px-4 py-2 bg-red-500/10 rounded">
                      {whepStatus.error}
                    </div>
                  )}
                  <div className="text-xs text-slate-500">
                    {isConnected ? '等待WHEP连接...' : '等待后端连接...'}
                  </div>
                  <button
                    onClick={connectWhep}
                    className="mt-4 px-4 py-2 text-[10px] font-black uppercase tracking-widest border border-white/20 text-white/80 hover:text-white hover:border-white/60 transition-all"
                  >
                    重新连接
                  </button>
                </div>
              )}

              {/* HUD 叠加 */}
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

              {/* 左上角信息 */}
              <div className="absolute top-4 left-4 z-10">
                <div className="bg-black/25 border-l-2 border-blue-500 px-3 py-2.5 font-mono text-[10px] flex flex-col gap-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className="text-white/40 uppercase">清晰度:</span>
                    <span className="text-slate-200 font-bold">{resolutionChip}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-white/40 uppercase">视频流:</span>
                    <span className={`font-bold ${currentWhep.color}`}>{currentWhep.text}</span>
                  </div>
                  <div className="pt-1.5 border-t border-white/10 text-white/35 uppercase">
                    信号: {telemetry ? `${telemetry.rssi_dbm} dBm` : '--'}
                  </div>
                </div>
                {isUiFullscreen && (
                  <div className="mt-2 bg-white/5 text-slate-400 px-2 py-1 rounded text-[9px] font-bold">
                    按 ESC 退出全屏
                  </div>
                )}
              </div>

              {!isUiFullscreen && (
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

              {/* 底部浮动控制栏 */}
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
                      {isMissionRunning ? <><Square size={14} fill="black" /><span>终止任务</span></> : <><Play size={14} fill="black" /><span>启动巡检</span></>}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* 右侧栏 (日志 + AI 检测) */}
            {!isUiFullscreen && (
              <aside className="w-64 bg-black flex flex-col shadow-[-10px_0_30px_rgba(0,0,0,0.5)]">
                {/* 可折叠日志区 */}
                <div className={`flex flex-col border-b border-white/20 transition-all duration-300 ${isLogExpanded ? 'h-1/3' : 'h-10'}`}>
                  <div
                    onClick={() => setIsLogExpanded(!isLogExpanded)}
                    className="flex items-center justify-between px-4 h-10 bg-white/10 cursor-pointer hover:bg-white hover:text-black transition-all group shrink-0"
                  >
                    <div className="flex items-center space-x-3 font-bold">
                      <Terminal size={14} />
                      <span className="text-[10px] uppercase tracking-widest font-black">终端状态</span>
                      <div className="flex space-x-1.5 ml-2">
                        {logRecentStatus.map((level, i) => (
                          <div key={i} className={`w-2 h-2 rounded-full border border-black/20 ${level === 'error' ? 'bg-red-500 shadow-[0_0_8px_red]' : level === 'warning' ? 'bg-orange-500' : 'bg-white'}`} />
                        ))}
                      </div>
                    </div>
                    {isLogExpanded ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
                  </div>
                  {isLogExpanded && (
                    <div className="flex-1 overflow-y-auto p-4 font-mono text-[10px] bg-black custom-scrollbar border-t border-white/5">
                      {logs.slice(-30).map((log, index) => (
                        <div key={`${log.timestamp}-${index}`} className="flex space-x-3 mb-2 border-b border-white/[0.05] pb-1">
                          <span className="text-slate-500 whitespace-nowrap">
                            [{new Date(log.timestamp * 1000).toLocaleTimeString([], { hour12: false, minute: '2-digit', second: '2-digit' })}]
                          </span>
                          <span className={
                            log.level === 'error' ? 'text-red-500 font-black' :
                            log.level === 'warning' ? 'text-orange-500 font-black' :
                            'text-slate-200 font-bold'
                          }>{log.level.charAt(0).toUpperCase()}</span>
                          <span className="text-slate-100 truncate leading-relaxed font-medium">[{log.module}] {log.message}</span>
                        </div>
                      ))}
                      <div ref={sidebarLogEndRef} />
                    </div>
                  )}
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
                      {isMissionRunning ? '终止任务' : '启动巡检'}
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
        ) : (
          /* 档案库页面 */
          <div className="flex-1 flex flex-col bg-black overflow-hidden p-8">
            <header className="flex flex-wrap items-end justify-between gap-4 mb-10 border-b border-white/20 pb-8">
              <div>
                <h1 className="text-4xl font-black tracking-tighter text-white mb-2 uppercase">数据档案库</h1>
                <p className="text-xs font-bold text-slate-400 uppercase tracking-widest">Digital Evidence & Analytics</p>
              </div>
              <div className="flex flex-wrap items-center gap-4">
                <div className="relative">
                  <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
                  <input
                    type="text"
                    placeholder="搜索告警..."
                    className="bg-zinc-900 border-2 border-white/20 rounded-lg py-3 pl-12 pr-6 text-sm font-bold text-white focus:outline-none focus:border-white transition-all w-80 placeholder:text-zinc-700"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                  />
                </div>
                <button
                  onClick={toggleAllEvidence}
                  className="px-4 py-3 text-[10px] font-black uppercase tracking-widest border-2 border-white/20 text-white hover:border-white transition-all"
                >
                  {filteredEvidence.length > 0 && filteredEvidence.every((item) => selectedEvidence.has(item.evidence_id)) ? '取消全选' : '全选'}
                </button>
                <button
                  onClick={deleteEvidenceSelected}
                  disabled={selectedEvidence.size === 0 || evidenceDeleting}
                  className={`px-4 py-3 text-[10px] font-black uppercase tracking-widest border-2 transition-all ${selectedEvidence.size === 0 || evidenceDeleting ? 'border-white/10 text-white/30 cursor-not-allowed' : 'border-red-500/60 text-red-300 hover:border-red-400 hover:text-red-200'}`}
                >
                  {evidenceDeleting ? '删除中' : `删除选中(${selectedEvidence.size})`}
                </button>
              </div>
            </header>
            <div className="flex-1 overflow-y-auto custom-scrollbar pb-10">
              {evidenceLoading ? (
                <div className="flex flex-col items-center justify-center h-full text-slate-500 space-y-4">
                  <ShieldCheck size={64} className="text-white/10" />
                  <p className="text-sm font-black uppercase tracking-widest text-white/20">加载中...</p>
                </div>
              ) : evidenceError ? (
                <div className="flex flex-col items-center justify-center h-full text-slate-500 space-y-4">
                  <ShieldCheck size={64} className="text-white/10" />
                  <p className="text-sm font-black uppercase tracking-widest text-white/20">加载失败</p>
                  <p className="text-xs text-red-400">{evidenceError}</p>
                </div>
              ) : filteredEvidence.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-slate-500 space-y-4">
                  <ShieldCheck size={64} className="text-white/10" />
                  <p className="text-sm font-black uppercase tracking-widest text-white/20">暂无告警记录</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-10">
                  {filteredEvidence.map((item, i) => {
                    const imageSrc = getImageUrl(item.image_url || undefined);
                    const confidence = item.confidence ?? undefined;
                    const timestamp = item.created_at || '';
                    return (
                      <div key={`${item.evidence_id}-${i}`} className="group bg-zinc-900 border-2 border-white/10 hover:border-white transition-all duration-500 rounded-2xl overflow-hidden flex flex-col shadow-[0_30px_60px_-12px_rgba(0,0,0,0.8)]">
                        {imageSrc && (
                          <div className="relative h-48 bg-black">
                            <img src={imageSrc} className="w-full h-full object-cover opacity-80 group-hover:opacity-100 group-hover:scale-105 transition-all duration-700" />
                            <div className="absolute top-5 left-5">
                              <span className={`px-3 py-1.5 rounded-sm font-black text-[10px] uppercase tracking-widest border-2 shadow-2xl ${
                                item.severity === 'CRITICAL' ? 'bg-red-600 border-red-400 text-white' : 'bg-black border-white text-white'
                              }`}>
                                {item.severity}
                              </span>
                            </div>
                            <div className="absolute top-5 right-5">
                              <button
                                onClick={() => deleteEvidenceSingle(item.evidence_id)}
                                className="px-2 py-1 text-[9px] font-black uppercase tracking-widest border border-red-500/60 text-red-300 hover:border-red-400 hover:text-red-200 bg-black/60"
                              >
                                删除
                              </button>
                            </div>
                            <div className="absolute bottom-4 right-4">
                              <input
                                type="checkbox"
                                checked={selectedEvidence.has(item.evidence_id)}
                                onChange={() => toggleEvidenceSelected(item.evidence_id)}
                              />
                            </div>
                          </div>
                        )}
                        <div className="p-6 flex-1 flex flex-col bg-zinc-900">
                          <h4 className="text-sm font-black text-white tracking-wide uppercase mb-4">{item.message || item.event_code || 'AI 告警'}</h4>
                          {confidence !== undefined && (
                            <div className="space-y-2 mb-4">
                              <div className="flex items-center justify-between text-[11px] font-black">
                                <span className="text-slate-500 uppercase tracking-widest">置信度</span>
                                <span className="font-mono text-white">{(confidence * 100).toFixed(1)}%</span>
                              </div>
                              <div className="h-2 bg-black rounded-full overflow-hidden border border-white/10">
                                <div className="h-full bg-white shadow-[0_0_15px_white]" style={{ width: `${confidence * 100}%` }} />
                              </div>
                            </div>
                          )}
                          <div className="pt-4 border-t border-white/10 flex items-center text-[10px] text-white font-black mt-auto">
                            <Clock size={14} className="mr-2 text-slate-500" />
                            <span>{timestamp ? new Date(timestamp).toLocaleString('zh-CN', { hour12: false }) : '--'}</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      {/* 配置面板模态框 */}
      {showConfigPanel && (
        <div className="fixed inset-0 bg-black/85 flex items-center justify-center z-[1000]">
          <div className="w-[800px] max-h-[90vh] overflow-auto rounded-lg">
            <ConfigPanel />
            <button
              onClick={() => setShowConfigPanel(false)}
              className="mt-4 w-full py-3 px-6 bg-red-500/20 border border-red-500/40 rounded-md text-red-300 text-xs font-bold cursor-pointer hover:bg-red-500/30 transition-all"
            >
              关闭配置
            </button>
          </div>
        </div>
      )}
    </div>
  );
}