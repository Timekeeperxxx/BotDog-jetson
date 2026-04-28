import { ArrowLeftRight, Camera, X } from 'lucide-react';
import type { PipControlsProps } from './types';

export function PipControls({
  isPipLarge,
  isPipHidden,
  pipLabel,
  pipStatus,
  pipDimensions,
  onTogglePipSize,
  onTogglePipHidden,
  onSwapCamera,
}: PipControlsProps) {
  if (isPipHidden) {
    return (
      <div
        className="absolute z-30 flex items-center justify-center cursor-pointer group/pip-restore"
        style={{ bottom: '108px', right: '16px', width: '48px', height: '48px' }}
        onClick={onTogglePipHidden}
        title="恢复画中画"
      >
        <div className="w-full h-full rounded-xl bg-black/80 border-2 border-white/20 group-hover/pip-restore:border-white/60 flex items-center justify-center transition-all shadow-lg">
          <Camera size={20} className="text-white/60 group-hover/pip-restore:text-white transition-colors" />
        </div>
        <div className={`absolute top-1 right-1 w-2 h-2 rounded-full ${
          pipStatus.status === 'connected' ? 'bg-emerald-500' :
          pipStatus.status === 'connecting' ? 'bg-amber-500 animate-pulse' : 'bg-red-500'
        }`} />
      </div>
    );
  }

  return (
    <div
      className="absolute z-30 cursor-pointer group/pip transition-all duration-300"
      style={{
        bottom: '108px',
        right: '16px',
        width: `${isPipLarge ? pipDimensions.largeWidth : pipDimensions.smallWidth}px`,
        height: `${isPipLarge ? pipDimensions.largeHeight : pipDimensions.smallHeight}px`,
      }}
      onClick={onTogglePipSize}
      title={isPipLarge ? '缩小画中画' : '放大画中画'}
    >
      <div className="absolute inset-0 rounded-lg border-2 border-white/25 group-hover/pip:border-white/60 shadow-[0_4px_30px_rgba(0,0,0,0.8)] transition-colors pointer-events-none" />
      <div className="absolute top-1.5 left-1.5 flex items-center space-x-1.5 bg-black/65 px-2 py-0.5 rounded text-[8px] font-mono font-black uppercase tracking-wider pointer-events-none">
        <div className={`w-1.5 h-1.5 rounded-full ${
          pipStatus.status === 'connected' ? 'bg-emerald-500' :
          pipStatus.status === 'connecting' ? 'bg-amber-500 animate-pulse' : 'bg-red-500'
        }`} />
        <span className="text-white/75">{pipLabel}</span>
      </div>
      <button
        className="absolute top-1.5 right-1.5 w-5 h-5 flex items-center justify-center bg-black/60 hover:bg-white/20 rounded transition-colors z-10"
        onClick={(e) => { e.stopPropagation(); onTogglePipHidden(); }}
        title="隐藏画中画"
      >
        <X size={10} className="text-white/75" />
      </button>
      <div className="absolute bottom-1.5 left-1/2 -translate-x-1/2 opacity-0 group-hover/pip:opacity-100 transition-opacity bg-black/60 px-1.5 py-0.5 rounded pointer-events-none">
        <span className="text-[8px] font-mono text-white/60">
          {isPipLarge
            ? `${pipDimensions.largeWidth}×${pipDimensions.largeHeight}`
            : `${pipDimensions.smallWidth}×${pipDimensions.smallHeight}`}
        </span>
      </div>
      <button
        className="absolute bottom-1.5 right-1.5 w-5 h-5 flex items-center justify-center bg-black/60 hover:bg-white/20 rounded transition-colors z-10"
        onClick={(e) => { e.stopPropagation(); onSwapCamera(); }}
        title="互换主画面与画中画"
      >
        <ArrowLeftRight size={10} className="text-white/75" />
      </button>
      {pipStatus.status !== 'connected' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/70 rounded-lg pointer-events-none">
          {pipStatus.status === 'connecting' ? (
            <div className="w-6 h-6 rounded-full border-2 border-white/20 border-t-white" style={{ animation: 'videoSpin 1s linear infinite' }} />
          ) : <Camera size={20} className="text-white/30" />}
          <span className="text-[9px] mt-1.5 font-bold text-white/40">
            {pipStatus.status === 'connecting' ? '连接中' : pipStatus.error || '未连接'}
          </span>
        </div>
      )}
    </div>
  );
}
