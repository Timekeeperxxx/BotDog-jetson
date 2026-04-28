import type { RefObject } from 'react';
import { Camera, ChevronDown, ChevronUp, ShieldCheck, Volume2, VolumeX } from 'lucide-react';
import { ControlPad } from '../ControlPad';
import { DetectionAlert } from '../alerts/DetectionAlert';
import { LogPanel } from '../logs/LogPanel';
import type { AlertEvent, AIStatus } from '../../types/event';
import type { LogEntry, SystemStatus } from '../../hooks/useBotDogWebSocket';
import type { WhepState } from '../../hooks/useWhepVideo';

export interface ConsoleRightPanelProps {
  logs: LogEntry[];
  isLogExpanded: boolean;
  onToggleLogExpanded: () => void;
  sidebarLogEndRef: RefObject<HTMLDivElement | null>;
  systemStatus: SystemStatus | null;
  isAudioPlaying: boolean;
  toggleAudio: () => void;
  aiStatus: AIStatus | null;
  isAiStatsExpanded: boolean;
  onToggleAiStatsExpanded: () => void;
  isMissionRunning: boolean;
  toggleMission: () => void;
  isConnected: boolean;
  whepStatus: WhepState;
  alerts: AlertEvent[];
  connectWs: () => void;
  connectWhep: () => void;
}

export function ConsoleRightPanel({
  logs,
  isLogExpanded,
  onToggleLogExpanded,
  sidebarLogEndRef,
  systemStatus,
  isAudioPlaying,
  toggleAudio,
  aiStatus,
  isAiStatsExpanded,
  onToggleAiStatsExpanded,
  isMissionRunning,
  toggleMission,
  isConnected,
  whepStatus,
  alerts,
  connectWs,
  connectWhep,
}: ConsoleRightPanelProps) {
  return (
    <aside className="w-64 bg-black flex flex-col shadow-[-10px_0_30px_rgba(0,0,0,0.5)]">
      <LogPanel
        logs={logs}
        isExpanded={isLogExpanded}
        onToggle={onToggleLogExpanded}
        sidebarLogEndRef={sidebarLogEndRef}
      />

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
        <div
          className="px-4 py-2 border-b border-white/10 bg-black/80 flex items-center justify-between cursor-pointer hover:bg-white/5 transition-all"
          onClick={onToggleAiStatsExpanded}
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
  );
}
