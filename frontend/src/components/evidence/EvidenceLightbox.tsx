import { Clock, Thermometer, X } from 'lucide-react';
import { getApiUrl } from '../../config/api';
import type { EvidenceItem } from '../../types/evidence';

function getImageUrl(imageUrl?: string | null): string | null {
  if (!imageUrl) return null;
  if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) {
    return imageUrl;
  }
  return getApiUrl(imageUrl);
}

export interface EvidenceLightboxProps {
  item: EvidenceItem | null;
  onClose: () => void;
}

export function EvidenceLightbox({ item, onClose }: EvidenceLightboxProps) {
  if (!item) return null;

  const lbImg = getImageUrl(item.image_url || undefined);
  const lbConf = item.confidence ?? undefined;

  return (
    <div
      className="fixed inset-0 z-[1100] bg-black/95 backdrop-blur-sm flex items-center justify-center"
      onClick={onClose}
    >
      <div
        className="relative flex flex-col max-w-4xl w-full mx-6 bg-zinc-900 border border-white/20 rounded-2xl overflow-hidden shadow-[0_40px_100px_rgba(0,0,0,1)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <div className="flex items-center space-x-3">
            <span className={`px-3 py-1.5 rounded-sm font-black text-[11px] uppercase tracking-widest border-2 ${
              item.severity === 'CRITICAL' ? 'bg-red-600 border-red-400 text-white' : 'bg-black border-white text-white'
            }`}>{item.severity}</span>
            <span className="text-white font-black text-sm tracking-wide">{item.message || item.event_code || 'AI 告警'}</span>
          </div>
          <button
            onClick={onClose}
            className="text-white/40 hover:text-white hover:bg-white/10 p-2 rounded-lg transition-all"
          >
            <X size={20} />
          </button>
        </div>
        <div className="bg-black flex items-center justify-center" style={{ minHeight: '420px' }}>
          {lbImg ? (
            <img src={lbImg} className="max-w-full max-h-[60vh] object-contain" />
          ) : (
            <div className="flex flex-col items-center justify-center py-24 text-white/20">
              <Thermometer size={64} className="mb-4" />
              <span className="text-xs uppercase tracking-widest font-black">无截图</span>
            </div>
          )}
        </div>
        <div className="px-6 py-5 border-t border-white/10 grid grid-cols-3 gap-6">
          {lbConf !== undefined && (
            <div className="col-span-2">
              <div className="flex items-center justify-between text-[11px] font-black mb-2">
                <span className="text-slate-500 uppercase tracking-widest">置信度</span>
                <span className="font-mono text-white">{(lbConf * 100).toFixed(1)}%</span>
              </div>
              <div className="h-2 bg-black rounded-full overflow-hidden border border-white/10">
                <div className="h-full bg-white shadow-[0_0_15px_white]" style={{ width: `${lbConf * 100}%` }} />
              </div>
            </div>
          )}
          <div className="flex items-center col-span-1 text-[11px] text-white/60 font-black">
            <Clock size={14} className="mr-2 text-slate-500 shrink-0" />
            <span>{item.created_at ? new Date(item.created_at).toLocaleString('zh-CN', { hour12: false }) : '--'}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
