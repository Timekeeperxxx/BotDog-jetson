import { useState } from 'react';
import { Camera, Maximize2, Minimize2, PenLine, Play, Square } from 'lucide-react';
import { TrackOverlay } from '../TrackOverlay1';
import { ZoneDrawer } from '../ZoneDrawer';
import { CameraVideo } from './CameraVideo';
import { OmniMonitorEntry } from './OmniMonitorEntry';
import { OmniMonitorOverlay } from './OmniMonitorOverlay';
import { VideoHud } from './VideoHud';
import type { VideoStageProps } from './types';

export function VideoStage({
  videoRef,
  isUiFullscreen,
  toggleFullscreen,
  trackOverlay,
  autoTrackEnabled,
  guardEnabled,
  isZoneDrawing,
  onToggleZoneDrawing,
  whepStatus,
  currentWhep,
  videoLatencyMs,
  videoResolution,
  resolutionChip,
  telemetry,
  isConnected,
  aiStatus,
  autoTrackFrames,
  autoTrack,
  connectWs,
  connectWhep,
  isMissionRunning,
  triggerSnapshot,
  toggleMission,
  frontWhepUrl,
  omniUrls,
}: VideoStageProps) {
  const [isOmniOpen, setIsOmniOpen] = useState(false);

  const mainOverlayEnabled = autoTrackEnabled || guardEnabled;
  const stageResolutionChip = resolutionChip || (videoResolution.height ? `${videoResolution.height}p` : '--');

  return (
    <div className="flex-1 flex min-h-0 relative">
      <div className={`flex-1 bg-black relative overflow-hidden transition-all duration-300 ${isUiFullscreen ? 'fixed inset-0 z-[100]' : 'border-r border-white/20'}`}>
        <CameraVideo videoRef={videoRef} />
        {trackOverlay && mainOverlayEnabled && (
          <TrackOverlay data={trackOverlay} videoRef={videoRef} />
        )}
        <ZoneDrawer
          frameW={trackOverlay?.frame_w ?? 1280}
          frameH={trackOverlay?.frame_h ?? 720}
          active={isZoneDrawing}
          onClose={onToggleZoneDrawing}
        />

        {whepStatus.status !== 'connected' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-900/88 z-5">
            <div className="text-5xl mb-4 opacity-50">
              {whepStatus.status === 'connecting' ? (
                <div className="w-12 h-12 rounded-full border-4 border-slate-200/20 border-t-slate-200 mx-auto" style={{ animation: 'videoSpin 1s linear infinite' }} />
              ) : whepStatus.status === 'error' ? (
                <span className="text-red-400 font-bold">x</span>
              ) : (
                <Camera size={48} className="text-white/30" />
              )}
            </div>
            <div className="text-lg font-bold text-slate-200 mb-2">视频流 {whepStatus.status === 'connecting' ? '连接中...' : whepStatus.error || '未连接'}</div>
            {whepStatus.error && (
              <div className="text-sm text-red-500 mb-4 px-4 py-2 bg-red-500/10 rounded">{whepStatus.error}</div>
            )}
            <div className="text-xs text-slate-500">{isConnected ? '等待WHEP连接...' : '等待后端连接...'}</div>
            <button onClick={connectWhep} className="mt-4 px-4 py-2 text-[10px] font-black uppercase tracking-widest border border-white/20 text-white/80 hover:text-white hover:border-white/60 transition-all">重新连接</button>
          </div>
        )}

        <OmniMonitorEntry onOpen={() => setIsOmniOpen(true)} />

        <div className="absolute inset-0 pointer-events-none p-6">
          <div className="h-full flex flex-col justify-between items-center relative">
            <div className="w-full flex justify-between">
              <div className="w-6 h-6 border-t-2 border-l-2 border-white/40" />
              <div className="w-6 h-6 border-t-2 border-r-2 border-white/40" />
            </div>
            <div className="w-40 h-40 border border-white/20 rounded-full flex items-center justify-center">
              <div className="w-8 h-[1px] bg-white/50" />
              <div className="w-[1px] h-8 bg-white/50 absolute" />
            </div>
            <div className="w-full flex justify-between">
              <div className="w-6 h-6 border-b-2 border-l-2 border-white/40" />
              <div className="w-6 h-6 border-b-2 border-r-2 border-white/40" />
            </div>
          </div>
        </div>

        <VideoHud
          resolutionChip={stageResolutionChip}
          currentWhep={currentWhep}
          whepStatus={whepStatus}
          telemetry={telemetry}
          isUiFullscreen={isUiFullscreen}
          aiStatus={aiStatus}
          autoTrackFrames={autoTrackFrames}
          isConnected={isConnected}
          videoLatencyMs={videoLatencyMs}
          autoTrack={autoTrack}
          connectWs={connectWs}
          connectWhep={connectWhep}
          isMissionRunning={isMissionRunning}
        />

        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 w-full max-w-lg px-6 z-30 pointer-events-auto">
          <div className="bg-black border-2 border-white/30 p-3 rounded-xl shadow-[0_20px_50px_rgba(0,0,0,1)] flex items-center justify-between px-8">
            <div className="flex items-center space-x-5 text-white">
              <button onClick={toggleFullscreen} className="p-2 hover:bg-white hover:text-black rounded-lg transition-all" title={isUiFullscreen ? '退出全屏' : '全屏'}>
                {isUiFullscreen ? <Minimize2 size={22} /> : <Maximize2 size={22} />}
              </button>
              <div className="h-8 w-px bg-white/30" />
              <button onClick={triggerSnapshot} className="p-2 hover:bg-white hover:text-black rounded-lg transition-all" title="拍照">
                <Camera size={22} />
              </button>
              <div className="h-8 w-px bg-white/30" />
              <button
                onClick={onToggleZoneDrawing}
                className={`p-2 rounded-lg transition-all ${
                  isZoneDrawing
                    ? 'bg-green-500 text-black'
                    : 'hover:bg-white hover:text-black text-white'
                }`}
                title={isZoneDrawing ? '退出画禁区模式' : '画禁区'}
              >
                <PenLine size={22} />
              </button>
            </div>
            <div className="flex items-center space-x-3">
              <span className={`text-[10px] font-black uppercase tracking-widest px-3 py-2 rounded border ${
                isMissionRunning
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                  : 'bg-white/5 text-slate-400 border-white/10'
              }`}>
                {isMissionRunning ? '巡检中' : '待命'}
              </span>
              <button
                onClick={toggleMission}
                disabled={!isConnected}
                className={`flex items-center space-x-4 px-12 py-3 rounded-lg font-black text-xs uppercase transition-all transform active:scale-95 shadow-xl disabled:opacity-40 disabled:cursor-not-allowed ${
                  isMissionRunning
                    ? 'bg-white text-black border-2 border-white'
                    : 'bg-white text-black ring-4 ring-white/20'
                }`}
              >
                {isMissionRunning ? <><Square size={14} fill="black" /><span>终止任务</span></> : <><Play size={14} fill="black" /><span>开始巡检</span></>}
              </button>
            </div>
          </div>
        </div>
      </div>

      <OmniMonitorOverlay
        open={isOmniOpen}
        onClose={() => setIsOmniOpen(false)}
        frontWhepUrl={frontWhepUrl}
        frontVideoRef={videoRef}
        omniUrls={omniUrls}
      />
    </div>
  );
}
