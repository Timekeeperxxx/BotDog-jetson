import { useEffect, useRef } from 'react';
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
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (item) dialogRef.current?.showModal();
  }, [item]);
  if (!item) return null;

  const lbImg = getImageUrl(item.image_url || undefined);
  const lbConf = item.confidence ?? undefined;

  return (
    <dialog
      ref={dialogRef}
      aria-label="告警记录详情"
      onCancel={onClose}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
      className="m-auto w-full max-w-4xl max-h-[90vh] overflow-y-auto bg-transparent text-white backdrop:bg-black/80"
    >
      <div
        className="relative flex flex-col max-w-4xl w-full bg-zinc-900 border border-white/20 rounded-2xl overflow-hidden shadow-[0_40px_100px_rgba(0,0,0,1)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <div className="flex items-center space-x-3">
            <span className={`px-3 py-1.5 rounded-sm font-black text-[11px] uppercase tracking-widest border-2 ${
              item.severity === 'CRITICAL' ? 'bg-red-600 border-red-400 text-white' : 'bg-black border-white text-white'
            }`}>{({ CRITICAL: '紧急', WARNING: '警告', INFO: '提示' } as Record<string, string>)[item.severity.toUpperCase()] || '提示'}</span>
            <span className="text-white font-black text-sm tracking-wide">{item.message || item.event_code || 'AI 告警'}</span>
          </div>
          <button
            aria-label="关闭详情"
            onClick={onClose}
            className="text-white/40 hover:text-white hover:bg-white/10 p-2 rounded-lg transition-all"
          >
            <X size={20} />
          </button>
        </div>
        <dl className="px-6 py-3 flex flex-wrap gap-x-6 gap-y-2 text-xs text-slate-300">
          <div><dt className="inline">记录编号：</dt><dd className="inline">{item.evidence_id}</dd></div>
          <div><dt className="inline">事件代码：</dt><dd className="inline">{item.event_code || item.event_type}</dd></div>
          {item.task_id != null && <div><dt className="inline">任务编号：</dt><dd className="inline">{item.task_id}</dd></div>}
          {item.gps_lat != null && item.gps_lon != null && <div><dt className="inline">位置：</dt><dd className="inline">{item.gps_lat}, {item.gps_lon}</dd></div>}
        </dl>
        <div className="bg-black flex items-center justify-center" style={{ minHeight: lbImg ? '320px' : '96px' }}>
          {lbImg ? (
            <img alt="告警现场截图" src={lbImg} className="max-w-full max-h-[60vh] object-contain" />
          ) : (
            <div className="flex flex-col items-center justify-center py-6 text-slate-400">
              <Thermometer size={32} className="mb-4" />
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
    </dialog>
  );
}
