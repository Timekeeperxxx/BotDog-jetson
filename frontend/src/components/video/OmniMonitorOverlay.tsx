import { useEffect, useRef, useState } from 'react';
import { Camera, RefreshCw, X } from 'lucide-react';
import { apiFetch } from '../../api/apiFetch';
import { useWhepVideo } from '../../hooks/useWhepVideo';
import type { OmniCameraUrls } from '../../hooks/useCameraSources';

interface OmniCellProps {
  label: string;
  whepUrl: string | undefined;
  active: boolean;
  fallbackHint?: string;
}

function OmniCell({ label, whepUrl, active, fallbackHint }: OmniCellProps) {
  const { status, videoRef, connect, disconnect } = useWhepVideo(whepUrl, { skipStats: true });

  useEffect(() => {
    if (!active) return;
    if (!whepUrl) return;
    connect();
    return () => { void disconnect(); };
  }, [active, whepUrl, connect, disconnect]);

  const dotColor =
    status.status === 'connected' ? 'bg-emerald-500'
    : status.status === 'connecting' ? 'bg-amber-500 animate-pulse'
    : 'bg-red-500';

  return (
    <div className="relative h-full bg-black border border-white/20 rounded-lg overflow-hidden">
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        className="absolute inset-0 w-full h-full object-cover bg-black"
      />
      <div className="absolute top-2 left-2 flex items-center gap-1.5 bg-black/70 px-2 py-1 rounded text-[10px] font-mono font-black uppercase tracking-widest">
        <div className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
        <span className="text-white/85">{label}</span>
      </div>
      {(!whepUrl || status.status !== 'connected') && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/75 pointer-events-none">
          {status.status === 'connecting' ? (
            <div className="w-8 h-8 rounded-full border-2 border-white/20 border-t-white" style={{ animation: 'videoSpin 1s linear infinite' }} />
          ) : (
            <Camera size={28} className="text-white/35" />
          )}
          <span className="mt-2 text-[10px] font-bold text-white/55">
            {!whepUrl ? (fallbackHint || '未配置推流') :
              status.status === 'connecting' ? '连接中' :
              status.status === 'error' ? (status.error || '连接错误') : '未连接'}
          </span>
        </div>
      )}
    </div>
  );
}

// 复用主界面已有的 MediaStream，不重新建立 WHEP 连接
function MirrorCell({ label, sourceRef, active }: {
  label: string;
  sourceRef: React.RefObject<HTMLVideoElement | null>;
  active: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (!active) return;
    const sync = () => {
      if (videoRef.current && sourceRef.current) {
        const stream = sourceRef.current.srcObject;
        if (stream && videoRef.current.srcObject !== stream) {
          videoRef.current.srcObject = stream;
        }
      }
    };
    sync();
    const timer = setInterval(sync, 500);
    return () => {
      clearInterval(timer);
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, [active, sourceRef]);

  return (
    <div className="relative h-full bg-black border border-white/20 rounded-lg overflow-hidden">
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        className="absolute inset-0 w-full h-full object-cover bg-black"
      />
      <div className="absolute top-2 left-2 flex items-center gap-1.5 bg-black/70 px-2 py-1 rounded text-[10px] font-mono font-black uppercase tracking-widest">
        <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
        <span className="text-white/85">{label}</span>
      </div>
    </div>
  );
}

interface OmniMonitorOverlayProps {
  open: boolean;
  onClose: () => void;
  frontWhepUrl: string | undefined;
  frontVideoRef?: React.RefObject<HTMLVideoElement | null>;
  omniUrls: OmniCameraUrls;
}

export function OmniMonitorOverlay({ open, onClose, frontWhepUrl, frontVideoRef, omniUrls }: OmniMonitorOverlayProps) {
  const [restarting, setRestarting] = useState(false);
  const [restartMessage, setRestartMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) {
      setRestartMessage(null);
      setRestarting(false);
    }
  }, [open]);

  const handleRestartPipeline = async () => {
    if (restarting) return;
    setRestarting(true);
    setRestartMessage(null);
    try {
      const result = await apiFetch<{ message?: string; pid?: number | null }>('/api/v1/system/pipeline/restart', {
        method: 'POST',
      });
      setRestartMessage(result.message || `已启动 Pipeline 重启${result.pid ? `，PID ${result.pid}` : ''}`);
    } catch (err) {
      setRestartMessage(err instanceof Error ? err.message : '重启 Pipeline 失败');
    } finally {
      setRestarting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[200] bg-black/95 backdrop-blur-sm flex flex-col">
      <div className="flex items-center justify-between px-6 py-3 border-b border-white/15">
        <div className="flex items-center gap-3">
          <div className="text-sm font-black uppercase tracking-[0.3em] text-white">全方位监控</div>
          <div className="text-[10px] font-mono text-white/40">FRONT · BACK · LEFT · RIGHT</div>
        </div>
        <div className="flex items-center gap-3">
          {restartMessage && (
            <div className="max-w-[320px] truncate text-[10px] font-bold text-white/55" title={restartMessage}>
              {restartMessage}
            </div>
          )}
          <button
            type="button"
            onClick={handleRestartPipeline}
            disabled={restarting}
            className="flex items-center gap-2 px-3 py-1.5 border border-amber-400/40 hover:border-amber-300 disabled:border-white/15 text-xs font-black uppercase tracking-widest text-amber-100/85 hover:text-amber-50 disabled:text-white/30 rounded transition-colors disabled:cursor-not-allowed"
            title="重启视频 Pipeline"
          >
            <RefreshCw size={14} className={restarting ? 'animate-spin' : ''} />
            <span>{restarting ? '重启中' : '重启 Pipeline'}</span>
          </button>
          <button
            onClick={onClose}
            className="flex items-center gap-2 px-3 py-1.5 border border-white/25 hover:border-white text-xs font-black uppercase tracking-widest text-white/75 hover:text-white rounded transition-colors"
            title="关闭 (Esc)"
          >
            <X size={14} />
            <span>关闭</span>
          </button>
        </div>
      </div>

      {/* 3×3 十字布局：四格等大，四角和中心留空 */}
      <div className="flex-1 grid grid-cols-3 grid-rows-3 gap-3 p-4">
        <div />
        {frontVideoRef
          ? <MirrorCell label="前 · AI" sourceRef={frontVideoRef} active={open} />
          : <OmniCell label="前 · AI" whepUrl={frontWhepUrl} active={open} />}
        <div />
        <OmniCell label="左" whepUrl={omniUrls.left} active={open} fallbackHint="cam3 未推流" />
        <div />
        <OmniCell label="右" whepUrl={omniUrls.right} active={open} fallbackHint="cam4 未推流" />
        <div />
        <OmniCell label="后" whepUrl={omniUrls.back} active={open} fallbackHint="cam2 未推流" />
        <div />
      </div>
    </div>
  );
}
