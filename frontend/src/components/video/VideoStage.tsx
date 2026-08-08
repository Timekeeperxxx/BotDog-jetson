import { useState } from 'react';
import { Camera, Gauge, Layers3, Maximize2, Minimize2, Play, SlidersHorizontal, Square, Video, VideoOff } from 'lucide-react';
import { TrackOverlay } from '../TrackOverlay1';
import { CameraControlPanel } from './CameraControlPanel';
import { CameraVideo } from './CameraVideo';
import { OmniMonitorEntry } from './OmniMonitorEntry';
import { OmniMonitorOverlay } from './OmniMonitorOverlay';
import { VideoHud } from './VideoHud';
import type { VideoStageProps } from './types';
import {
  AI_OVERLAY_LAYERS_STORAGE_KEY,
  DEFAULT_AI_OVERLAY_VISIBILITY,
  getInitialAiOverlayVisibility,
  hasVisibleAiOverlayLayer,
  type AiOverlayLayer,
} from './videoStagePreferences';

const AI_LAYER_OPTIONS: Array<{
  key: AiOverlayLayer;
  label: string;
  description: string;
  color: string;
}> = [
  { key: 'helmet', label: '安全帽检测', description: '人员、头部、安全帽', color: '#facc15' },
  { key: 'weapon', label: '武器检测', description: '枪械、刀具', color: '#fb7185' },
  { key: 'pose', label: '姿态检测', description: '人体框、骨架、姿态', color: '#2dd4bf' },
  { key: 'face', label: '人脸身份', description: '姓名和识别状态', color: '#4ade80' },
  { key: 'tracking', label: '跟踪与防区', description: '锁定框、辅助线、防区', color: '#60a5fa' },
];

export function VideoStage({
  videoRef,
  isUiFullscreen,
  toggleFullscreen,
  trackOverlay,
  autoTrackEnabled,
  guardEnabled,
  whepStatus,
  currentWhep,
  videoLatencyMs,
  videoLatencyStats,
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
  isRecording,
  onToggleRecording,
  videoProfile,
  onVideoProfileChange,
}: VideoStageProps) {
  const [isOmniOpen, setIsOmniOpen] = useState(false);
  const [isCameraControlOpen, setIsCameraControlOpen] = useState(false);
  const [isAiLayerPanelOpen, setIsAiLayerPanelOpen] = useState(false);
  const [aiOverlayVisibility, setAiOverlayVisibility] = useState(() => {
    if (typeof window === 'undefined') return getInitialAiOverlayVisibility(null);
    return getInitialAiOverlayVisibility(window.localStorage);
  });

  const updateAiOverlayVisibility = (
    updater: (current: typeof aiOverlayVisibility) => typeof aiOverlayVisibility,
  ) => {
    setAiOverlayVisibility((current) => {
      const next = updater(current);
      window.localStorage.setItem(AI_OVERLAY_LAYERS_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  };

  const toggleAiLayer = (layer: AiOverlayLayer) => {
    updateAiOverlayVisibility((current) => ({ ...current, [layer]: !current[layer] }));
  };

  const allAiLayersVisible = Object.values(aiOverlayVisibility).every(Boolean);
  const activeAiLayerCount = Object.values(aiOverlayVisibility).filter(Boolean).length;
  const toggleAllAiLayers = () => {
    const nextVisible = !allAiLayersVisible;
    updateAiOverlayVisibility(() => Object.fromEntries(
      Object.keys(DEFAULT_AI_OVERLAY_VISIBILITY).map((key) => [key, nextVisible]),
    ) as typeof aiOverlayVisibility);
  };

  const mainOverlayEnabled = hasVisibleAiOverlayLayer(aiOverlayVisibility) && (
    autoTrackEnabled
      || guardEnabled
      || Boolean(trackOverlay?.poses?.length)
      || Boolean(trackOverlay?.detections?.length)
  );
  const stageResolutionChip = resolutionChip || (videoResolution.height ? `${videoResolution.height}p` : '--');

  return (
    <div className="flex-1 flex min-h-0 relative">
      <div className={`flex-1 bg-black relative overflow-hidden transition-all duration-300 ${isUiFullscreen ? 'fixed inset-0 z-[100]' : 'border-r border-white/20'}`}>
        <CameraVideo videoRef={videoRef} />
        {trackOverlay && mainOverlayEnabled && (
          <TrackOverlay
            data={trackOverlay}
            videoRef={videoRef}
            visibility={aiOverlayVisibility}
          />
        )}
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
          videoLatencyStats={videoLatencyStats}
          autoTrack={autoTrack}
          connectWs={connectWs}
          connectWhep={connectWhep}
          isMissionRunning={isMissionRunning}
        />

        <CameraControlPanel
          open={isCameraControlOpen}
          onClose={() => setIsCameraControlOpen(false)}
        />

        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 w-full max-w-4xl px-6 z-30 pointer-events-auto">
          <div className="bg-black border-2 border-white/30 p-3 rounded-xl shadow-[0_20px_50px_rgba(0,0,0,1)] flex items-center justify-between px-8">
            <div className="flex items-center space-x-5 text-white">
              <button onClick={toggleFullscreen} className="p-2 hover:bg-white hover:text-black rounded-lg transition-all" title={isUiFullscreen ? '退出全屏' : '全屏'}>
                {isUiFullscreen ? <Minimize2 size={22} /> : <Maximize2 size={22} />}
              </button>
              <div className="h-8 w-px bg-white/30" />
              <button onClick={triggerSnapshot} className="p-2 hover:bg-white hover:text-black rounded-lg transition-all" title="拍照">
                <Camera size={22} />
              </button>
              {onToggleRecording && (
                <button
                  onClick={onToggleRecording}
                  className={`p-2 rounded-lg transition-all ${isRecording ? 'text-red-400 hover:bg-red-500/20' : 'hover:bg-white hover:text-black'}`}
                  title={isRecording ? '停止录像' : '开始录像'}
                >
                  {isRecording ? (
                    <VideoOff size={22} className="animate-pulse" />
                  ) : (
                    <Video size={22} />
                  )}
                </button>
              )}
              <button
                onClick={() => onVideoProfileChange(videoProfile === 'remote' ? 'main' : 'remote')}
                className={`min-w-[88px] px-2 py-2 rounded-lg transition-all flex items-center justify-center gap-2 ${
                  videoProfile === 'remote'
                    ? 'bg-cyan-400 text-black'
                    : 'hover:bg-white hover:text-black'
                }`}
                title={videoProfile === 'remote' ? '切换到高清主流' : '切换到低延迟远程流'}
              >
                <Gauge size={22} />
                <span className="text-[10px] font-black">{videoProfile === 'remote' ? '低延迟' : '高清'}</span>
              </button>
              <button
                onClick={() => setIsCameraControlOpen((value) => !value)}
                className={`p-2 rounded-lg transition-all ${
                  isCameraControlOpen
                    ? 'bg-cyan-300 text-black'
                    : 'hover:bg-white hover:text-black'
                }`}
                title="相机调节"
                aria-label="相机调节"
                aria-expanded={isCameraControlOpen}
              >
                <SlidersHorizontal size={22} />
              </button>
              <div className="relative">
                <button
                  onClick={() => setIsAiLayerPanelOpen((open) => !open)}
                  className={`relative p-2 rounded-lg transition-all ${
                    isAiLayerPanelOpen || activeAiLayerCount < AI_LAYER_OPTIONS.length
                      ? 'bg-emerald-300/15 text-emerald-200 hover:bg-emerald-300/25'
                      : 'hover:bg-white hover:text-black'
                  }`}
                  title="选择 AI 检测叠层"
                  aria-label="AI 检测叠层"
                  aria-expanded={isAiLayerPanelOpen}
                  aria-controls="ai-layer-popover"
                >
                  <Layers3 size={22} />
                  <span className="absolute -right-1 -top-1 min-w-4 rounded-full bg-emerald-300 px-1 text-center text-[9px] font-black leading-4 text-black">
                    {activeAiLayerCount}
                  </span>
                </button>

                {isAiLayerPanelOpen && (
                  <div
                    id="ai-layer-popover"
                    role="group"
                    aria-label="AI 检测叠层显示开关"
                    className="absolute bottom-[calc(100%+14px)] left-1/2 z-50 w-72 -translate-x-1/2 rounded-xl border border-white/20 bg-[#070e14]/98 p-3 text-left shadow-[0_18px_55px_rgba(0,0,0,0.72)] backdrop-blur"
                  >
                    <div className="mb-2 flex items-center justify-between border-b border-white/10 pb-2">
                      <div>
                        <div className="text-xs font-black text-white">AI 检测叠层</div>
                        <div className="mt-0.5 text-[10px] text-white/45">仅控制显示，不会停用模型</div>
                      </div>
                      <button
                        type="button"
                        onClick={toggleAllAiLayers}
                        className="rounded-md border border-white/15 px-2 py-1 text-[10px] font-bold text-white/70 transition hover:border-white/40 hover:text-white"
                      >
                        {allAiLayersVisible ? '全部隐藏' : '全部显示'}
                      </button>
                    </div>

                    <div className="grid gap-1.5">
                      {AI_LAYER_OPTIONS.map((option) => {
                        const active = aiOverlayVisibility[option.key];
                        return (
                          <button
                            key={option.key}
                            type="button"
                            onClick={() => toggleAiLayer(option.key)}
                            aria-pressed={active}
                            className={`flex min-h-11 items-center gap-3 rounded-lg border px-3 py-2 transition ${
                              active
                                ? 'border-emerald-300/35 bg-emerald-300/10 text-white'
                                : 'border-white/10 bg-white/[0.03] text-white/45 hover:border-white/25 hover:text-white/70'
                            }`}
                          >
                            <span
                              className="h-2.5 w-2.5 shrink-0 rounded-full ring-2 ring-white/10"
                              style={{ backgroundColor: option.color }}
                            />
                            <span className="min-w-0 flex-1">
                              <span className="block text-[11px] font-black">{option.label}</span>
                              <span className="block truncate text-[9px] font-medium opacity-55">{option.description}</span>
                            </span>
                            <span className={`relative h-5 w-9 shrink-0 rounded-full transition ${active ? 'bg-emerald-300' : 'bg-white/15'}`}>
                              <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-black shadow transition-transform ${active ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
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
