import { Clock, Search, ShieldCheck, Thermometer } from 'lucide-react';
import { getApiUrl } from '../../config/api';
import { EvidenceLightbox } from './EvidenceLightbox';
import type { UseEvidenceState } from '../../hooks/useEvidence';

function getImageUrl(imageUrl?: string | null): string | null {
  if (!imageUrl) return null;
  if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) {
    return imageUrl;
  }
  return getApiUrl(imageUrl);
}

export interface EvidencePanelProps {
  evidence: UseEvidenceState;
}

export function EvidencePanel({ evidence }: EvidencePanelProps) {
  const {
    searchQuery,
    setSearchQuery,
    evidenceLoading,
    evidenceError,
    selectedEvidence,
    evidenceDeleting,
    filteredEvidence,
    toggleAllEvidence,
    deleteEvidenceSelected,
    deleteEvidenceSingle,
    toggleEvidenceSelected,
    lightboxItem,
    setLightboxItem,
  } = evidence;

  return (
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
                <div
                  key={`${item.evidence_id}-${i}`}
                  onClick={() => setLightboxItem(item)}
                  className="group bg-zinc-900 border-2 border-white/10 hover:border-white transition-all duration-500 rounded-2xl overflow-hidden flex flex-col shadow-[0_30px_60px_-12px_rgba(0,0,0,0.8)] cursor-pointer"
                >
                  <div className="relative h-48 bg-black shrink-0">
                    {imageSrc ? (
                      <img src={imageSrc} className="w-full h-full object-cover opacity-80 group-hover:opacity-100 group-hover:scale-105 transition-all duration-700" />
                    ) : (
                      <div className="w-full h-full flex flex-col items-center justify-center bg-zinc-800/60">
                        <Thermometer size={36} className="text-white/20 mb-1" />
                        <span className="text-[9px] uppercase tracking-widest text-white/20 font-black">无截图</span>
                      </div>
                    )}
                    <div className="absolute top-5 left-5">
                      <span className={`px-3 py-1.5 rounded-sm font-black text-[10px] uppercase tracking-widest border-2 shadow-2xl ${
                        item.severity === 'CRITICAL' ? 'bg-red-600 border-red-400 text-white' : 'bg-black border-white text-white'
                      }`}>
                        {item.severity}
                      </span>
                    </div>
                    <div className="absolute top-5 right-5">
                      <button
                        onClick={(e) => { e.stopPropagation(); deleteEvidenceSingle(item.evidence_id); }}
                        className="px-2 py-1 text-[9px] font-black uppercase tracking-widest border border-red-500/60 text-red-300 hover:border-red-400 hover:text-red-200 bg-black/60"
                      >
                        删除
                      </button>
                    </div>
                    <div className="absolute bottom-4 right-4">
                      <input
                        type="checkbox"
                        checked={selectedEvidence.has(item.evidence_id)}
                        onChange={(e) => { e.stopPropagation(); toggleEvidenceSelected(item.evidence_id); }}
                        onClick={(e) => e.stopPropagation()}
                        className="w-4 h-4 accent-white cursor-pointer"
                      />
                    </div>
                  </div>
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
      <EvidenceLightbox item={lightboxItem} onClose={() => setLightboxItem(null)} />
    </div>
  );
}
