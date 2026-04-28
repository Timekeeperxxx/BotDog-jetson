import type { AIStatus } from '../../types/event';
import type { TelemetryData } from '../../hooks/useBotDogWebSocket';

export interface StatusWidgetsProps {
  resolutionChip: string;
  whepStatusText: string;
  whepStatusColor: string;
  telemetry: TelemetryData | null;
  isUiFullscreen: boolean;
  aiStatus: AIStatus | null;
  autoTrackFrames: number;
}

export function StatusWidgets({
  resolutionChip,
  whepStatusText,
  whepStatusColor,
  telemetry,
  isUiFullscreen,
  aiStatus,
  autoTrackFrames,
}: StatusWidgetsProps) {
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
            <span className={`font-bold ${whepStatusColor}`}>{whepStatusText}</span>
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
    </>
  );
}
