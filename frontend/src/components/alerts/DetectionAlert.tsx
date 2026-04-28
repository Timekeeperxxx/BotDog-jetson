import { getApiUrl } from '../../config/api';
import type { AlertEvent } from '../../types/event';

function getImageUrl(imageUrl?: string | null): string | null {
  if (!imageUrl) return null;
  if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) {
    return imageUrl;
  }
  return getApiUrl(imageUrl);
}

export interface DetectionAlertProps {
  data: AlertEvent;
}

export function DetectionAlert({ data }: DetectionAlertProps) {
  const isStranger = data.severity === 'CRITICAL';
  const imageSrc = getImageUrl(data.image_url);
  const severityLabel: Record<string, string> = {
    CRITICAL: '紧急告警',
    WARNING: '警告',
    INFO: '提示',
  };
  const displaySeverity = severityLabel[data.severity] ?? data.severity;

  return (
    <div className="group bg-zinc-900 border-2 border-white/10 p-3 rounded-xl shadow-2xl hover:border-white transition-all cursor-pointer">
      <div className="flex items-center justify-between mb-3 border-b border-white/5 pb-2">
        <div className="flex items-center space-x-2">
          <div className={`w-2 h-2 rounded-full ${isStranger ? 'bg-red-500 animate-pulse' : 'bg-orange-500'}`} />
          <span className="text-[10px] font-black tracking-widest text-white">
            {displaySeverity}
          </span>
        </div>
        <span className="text-[10px] font-mono font-black text-slate-400">
          {new Date(data.timestamp).toLocaleTimeString('zh-CN', { hour12: false })}
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
