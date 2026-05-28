import { useEffect, useState, useRef } from 'react';
import { Clock, Search, ShieldCheck, Thermometer, Video, X } from 'lucide-react';
import { getApiUrl } from '../../config/api';
import { EvidenceLightbox } from './EvidenceLightbox';
import { useRecordings, type RecordingItem } from '../../hooks/useRecordings';
import type { UseEvidenceState } from '../../hooks/useEvidence';

function getImageUrl(imageUrl?: string | null): string | null {
  if (!imageUrl) return null;
  if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) {
    return imageUrl;
  }
  return getApiUrl(imageUrl);
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '--';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatFileSize(bytes: number | null): string {
  if (bytes === null) return '--';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function RecordingVideoModal({ item, onClose }: { item: RecordingItem; onClose: () => void }) {
  const videoSrc = item.video_url.startsWith('http') ? item.video_url : getApiUrl(item.video_url);
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
            <Video size={16} className="text-white/60" />
            <span className="text-white font-black text-sm tracking-wide">
              {new Date(item.started_at).toLocaleString('zh-CN', { hour12: false })}
            </span>
            <span className="text-xs text-slate-500 font-black uppercase tracking-widest">
              {item.camera_name} · {formatDuration(item.duration_seconds)} · {formatFileSize(item.file_size_bytes)}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-white/40 hover:text-white hover:bg-white/10 p-2 rounded-lg transition-all"
          >
            <X size={20} />
          </button>
        </div>
        <div className="bg-black flex items-center justify-center" style={{ minHeight: '420px' }}>
          <video
            src={videoSrc}
            controls
            autoPlay
            className="max-w-full max-h-[60vh] w-full"
          />
        </div>
      </div>
    </div>
  );
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

  const [activeSubTab, setActiveSubTab] = useState<'evidence' | 'recordings'>('evidence');
  const [videoModalItem, setVideoModalItem] = useState<RecordingItem | null>(null);
  const { recordings, loading: recLoading, error: recError, fetchRecordings } = useRecordings();
  const fetchedRef = useRef(false);

  useEffect(() => {
    if (activeSubTab === 'recordings' && !fetchedRef.current) {
      fetchedRef.current = true;
      void fetchRecordings();
    }
  }, [activeSubTab, fetchRecordings]);

  return (
    <div className="flex-1 flex flex-col bg-black overflow-hidden p-8">
      <header className="flex flex-wrap items-end justify-between gap-4 mb-6 border-b border-white/20 pb-6">
        <div>
          <h1 className="text-4xl font-black tracking-tighter text-white mb-2 uppercase">数据档案库</h1>
          <p className="text-xs font-bold text-slate-400 uppercase tracking-widest">Digital Evidence & Analytics</p>
        </div>

        {/* Sub-tab 切换 */}
        <div className="flex items-center border-2 border-white/20 rounded-lg overflow-hidden">
          <button
            onClick={() => setActiveSubTab('evidence')}
            className={`px-5 py-2.5 text-[10px] font-black uppercase tracking-widest transition-all ${
              activeSubTab === 'evidence' ? 'bg-white text-black' : 'text-slate-400 hover:text-white'
            }`}
          >
            截图告警
          </button>
          <button
            onClick={() => { setActiveSubTab('recordings'); if (!fetchedRef.current) { fetchedRef.current = true; void fetchRecordings(); } }}
            className={`px-5 py-2.5 text-[10px] font-black uppercase tracking-widest transition-all ${
              activeSubTab === 'recordings' ? 'bg-white text-black' : 'text-slate-400 hover:text-white'
            }`}
          >
            录像
          </button>
        </div>

        {/* 截图告警操作栏 */}
        {activeSubTab === 'evidence' && (
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
        )}

        {/* 录像操作栏 */}
        {activeSubTab === 'recordings' && (
          <button
            onClick={() => { fetchedRef.current = true; void fetchRecordings(); }}
            className="px-4 py-3 text-[10px] font-black uppercase tracking-widest border-2 border-white/20 text-white hover:border-white transition-all"
          >
            刷新
          </button>
        )}
      </header>

      <div className="flex-1 overflow-y-auto custom-scrollbar pb-10">

        {/* ── 截图告警列表 ── */}
        {activeSubTab === 'evidence' && (
          evidenceLoading ? (
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
          )
        )}

        {/* ── 录像列表 ── */}
        {activeSubTab === 'recordings' && (
          recLoading ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-500 space-y-4">
              <Video size={64} className="text-white/10" />
              <p className="text-sm font-black uppercase tracking-widest text-white/20">加载中...</p>
            </div>
          ) : recError ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-500 space-y-4">
              <Video size={64} className="text-white/10" />
              <p className="text-sm font-black uppercase tracking-widest text-white/20">加载失败</p>
              <p className="text-xs text-red-400">{recError}</p>
            </div>
          ) : recordings.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-500 space-y-4">
              <Video size={64} className="text-white/10" />
              <p className="text-sm font-black uppercase tracking-widest text-white/20">暂无录像记录</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-10">
              {recordings.map((rec) => (
                <div
                  key={rec.recording_id}
                  onClick={() => setVideoModalItem(rec)}
                  className="group bg-zinc-900 border-2 border-white/10 hover:border-white transition-all duration-500 rounded-2xl overflow-hidden flex flex-col shadow-[0_30px_60px_-12px_rgba(0,0,0,0.8)] cursor-pointer"
                >
                  <div className="relative h-48 bg-black shrink-0 flex items-center justify-center">
                    <Video size={48} className="text-white/20 group-hover:text-white/40 transition-colors duration-500" />
                    {rec.ended_at === null && (
                      <div className="absolute top-5 left-5">
                        <span className="px-3 py-1.5 rounded-sm font-black text-[10px] uppercase tracking-widest border-2 bg-red-600 border-red-400 text-white animate-pulse">
                          录制中
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="p-6 flex-1 flex flex-col bg-zinc-900">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs font-black text-slate-400 uppercase tracking-widest">{rec.camera_name}</span>
                      <span className="text-xs font-mono text-white">{formatDuration(rec.duration_seconds)}</span>
                    </div>
                    <div className="text-[11px] text-slate-500 font-black mb-4">{formatFileSize(rec.file_size_bytes)}</div>
                    <div className="pt-4 border-t border-white/10 flex items-center text-[10px] text-white font-black mt-auto">
                      <Clock size={14} className="mr-2 text-slate-500" />
                      <span>{new Date(rec.started_at).toLocaleString('zh-CN', { hour12: false })}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )
        )}
      </div>

      <EvidenceLightbox item={lightboxItem} onClose={() => setLightboxItem(null)} />
      {videoModalItem && (
        <RecordingVideoModal item={videoModalItem} onClose={() => setVideoModalItem(null)} />
      )}
    </div>
  );
}
