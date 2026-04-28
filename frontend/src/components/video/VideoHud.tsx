import { AutoTrackPanel } from '../AutoTrackPanel';
import type { VideoHudProps } from './types';

export function VideoHud({
  resolutionChip,
  currentWhep,
  whepStatus,
  telemetry,
  isUiFullscreen,
  aiStatus,
  autoTrackFrames,
  isConnected,
  videoLatencyMs,
  autoTrack,
  connectWs,
  connectWhep,
  isMissionRunning,
}: VideoHudProps) {
  return (
    <>
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

      <div className="absolute bottom-20 left-4 z-10 font-mono text-[10px]">
        <div className="bg-black/50 border-l-2 border-emerald-500/60 px-2.5 py-1.5 flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="text-white/40 uppercase">AI帧</span>
            <span className={`font-black ${aiStatus ? 'text-emerald-400' : 'text-red-400'}`}>
              {aiStatus?.frames_processed ?? 0}
            </span>
            {!aiStatus && <span className="text-red-400/80">无数据</span>}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-white/40 uppercase">检出</span>
            <span className="font-black text-amber-400">{aiStatus?.detections_count ?? 0}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-white/40 uppercase">跟踪帧</span>
            <span className="font-black text-cyan-400">{autoTrackFrames}</span>
          </div>
        </div>
      </div>

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
    </>
  );
}
