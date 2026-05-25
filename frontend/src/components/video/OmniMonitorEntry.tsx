import { Grid3x3 } from 'lucide-react';

interface OmniMonitorEntryProps {
  onOpen: () => void;
}

export function OmniMonitorEntry({ onOpen }: OmniMonitorEntryProps) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group absolute z-30 flex flex-col items-center justify-center bg-black/80 border-2 border-white/25 hover:border-white/60 rounded-xl shadow-[0_4px_30px_rgba(0,0,0,0.8)] transition-all"
      style={{ bottom: '108px', right: '16px', width: '120px', height: '120px' }}
      title="开启全方位监控（4 路画面）"
    >
      <Grid3x3 size={32} className="text-white/70 group-hover:text-white transition-colors" />
      <div className="mt-2 text-[10px] font-black uppercase tracking-widest text-white/80 group-hover:text-white">
        全方位监控
      </div>
      <div className="mt-0.5 text-[9px] font-mono text-white/40">前 · 后 · 左 · 右</div>
    </button>
  );
}
