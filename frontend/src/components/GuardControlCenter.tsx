import React, { useEffect, useRef } from 'react';
import {
  Shield, ShieldAlert, AlertTriangle, RefreshCcw, Hand,
  Crosshair, Activity, Clock, Settings, Camera, Octagon, Eye, Terminal,
  Volume2, VolumeX
} from 'lucide-react';
import { TrackOverlay, TrackOverlayData } from './TrackOverlay';

export interface GuardStatus {
  enabled: boolean;
  state: string;
  intrusion_counter: number;
  confirm_frames: number;
  clear_counter: number;
  clear_frames: number;
  guard_duration_s: number;
  zone_quality: number;
  zone_lost_frames: number;
  current_zone_bbox: [number, number, number, number] | null;
  start_zone_bbox: [number, number, number, number] | null;
}

const GUARD_STATES: Record<string, any> = {
  STANDBY: { label: '待命巡检', desc: '颜色检测中，防区已锁定', color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', icon: Shield },
  ADVANCING: { label: '驱离执行中', desc: '目标入侵，战术推进中', color: 'text-red-500', bg: 'bg-red-500/10', border: 'border-red-500/50', icon: ShieldAlert, pulse: true },
  RETURNING: { label: '视觉返航中', desc: '目标已清空，归位中', color: 'text-blue-400', bg: 'bg-blue-500/10', border: 'border-blue-500/30', icon: RefreshCcw },
  LOST_ZONE: { label: '区域丢失保护', desc: '特征丢失，停机保护', color: 'text-orange-500', bg: 'bg-orange-500/10', border: 'border-orange-500/50', icon: AlertTriangle, pulse: true },
  MANUAL_OVERRIDE: { label: '人工接管', desc: '系统已被遥控器接管', color: 'text-zinc-500', bg: 'bg-zinc-800/50', border: 'border-zinc-700', icon: Hand },
};

export interface GuardControlCenterProps {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  whepStatus: { status: string; error?: string | null };
  connectWhep: () => void;
  videoLatencyMs: number | null;
  trackOverlay: TrackOverlayData | null;
  guardStatus: GuardStatus | null;
  onToggleEnable: () => void;
  onEmergencyStop: () => void;
  logs: { timestamp: number; level: string; module: string; message: string }[];
  isAudioPlaying: boolean;
  onAudioToggle: () => void;
}

export function GuardControlCenter({
  videoRef,
  whepStatus,
  connectWhep,
  videoLatencyMs,
  trackOverlay,
  guardStatus,
  onToggleEnable,
  onEmergencyStop,
  logs,
  isAudioPlaying,
  onAudioToggle,
}: GuardControlCenterProps) {
  // Use safe default for status (ensure it behaves correctly if not connected)
  const safeStatus = guardStatus || {
    enabled: false,
    state: 'STANDBY',
    intrusion_counter: 0,
    confirm_frames: 15,
    clear_counter: 0,
    clear_frames: 30,
    guard_duration_s: 0,
    zone_quality: 0.0,
    zone_lost_frames: 0,
    current_zone_bbox: null,
    start_zone_bbox: null,
  };

  const currentStateInfo = GUARD_STATES[safeStatus.state] || GUARD_STATES.STANDBY;
  
  const getQualityColor = (q: number) => {
    if (q >= 0.7) return 'text-emerald-400 bg-emerald-500';
    if (q >= 0.3) return 'text-amber-400 bg-amber-500';
    return 'text-red-500 bg-red-500';
  };

  const logsEndRef = useRef<HTMLDivElement | null>(null);
  
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  // filter logs to only show GUARD-related messages if possible
  const guardLogs = logs.filter(l => l.module === 'GUARD' || l.module === 'APP').slice(-50);

  return (
    <div className="flex-1 flex min-h-0 bg-[#050506]">
      {/* 1. 中央大屏主视图 */}
      <div className="flex-1 flex flex-col relative min-w-0 border-r border-white/20">
        
        {/* 顶部简易面包屑 */}
        <div className="h-12 border-b border-white/20 bg-black flex items-center px-6 gap-4 z-20">
           <Shield className="w-4 h-4 text-white" />
           <h1 className="text-xs font-black tracking-widest text-white uppercase">自动驱离控制中心</h1>
           <div className="h-3 w-px bg-white/30"></div>
           <span className="px-2 py-0.5 rounded bg-white/10 text-[9px] text-white/50 font-mono font-bold tracking-widest uppercase">VISION_GUARD_V2</span>
        </div>

        {/* 沉浸式视频区 */}
        <div className="flex-1 bg-black relative overflow-hidden flex items-center justify-center">
            
          <video
            ref={videoRef}
            autoPlay playsInline muted
            className="absolute inset-0 w-full h-full object-cover z-0"
          />

          {trackOverlay && safeStatus.enabled && (
            <TrackOverlay data={trackOverlay} videoRef={videoRef} />
          )}

          {/* 如果没连接 */}
          {whepStatus.status !== 'connected' && (
             <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 z-10">
                <Camera className="w-24 h-24 text-white/10" />
                <span className="text-white/30 font-mono font-bold tracking-widest mt-4">NO_VIDEO_SIGNAL</span>
                <span className="text-white/20 mt-2 text-xs font-bold">{whepStatus.status === 'connecting' ? '连接中...' : whepStatus.error || '未连接'}</span>
                <button onClick={connectWhep} className="mt-6 px-4 py-2 text-[10px] font-black uppercase tracking-widest border border-white/20 text-white/80 hover:text-white hover:border-white/60 transition-all rounded">
                  重新连接
                </button>
             </div>
          )}

          {/* OSD: 视野网格 */}
          <div className="absolute inset-0 z-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:40px_40px] pointer-events-none mix-blend-overlay"></div>
          
          {/* 左上角状态信息 */}
          <div className="absolute top-4 left-4 flex flex-col gap-2 z-30 pointer-events-none">
            <div className="bg-black/60 backdrop-blur-sm border border-white/20 p-3 rounded flex flex-col gap-1.5 font-mono text-[10px] uppercase tracking-widest">
              <div className="flex items-center gap-2 text-white/40"><Eye className="w-3.5 h-3.5" /> 视觉引擎: <span className={safeStatus.enabled ? "text-emerald-400 font-black" : "text-zinc-500 font-bold"}>{safeStatus.enabled ? 'ONLINE' : 'OFFLINE'}</span></div>
              <div className="flex items-center gap-2 text-white/40"><Activity className="w-3.5 h-3.5" /> 目标锁定: <span className="text-white font-bold">{safeStatus.enabled && safeStatus.zone_quality > 0.3 ? 'TRUE' : 'FALSE'}</span></div>
              <div className="flex items-center gap-2 text-white/40"><Crosshair className="w-3.5 h-3.5" /> 跟踪模式: <span className="text-blue-400 font-bold">HSV_ZONE_V2</span></div>
            </div>
            {videoLatencyMs !== null && (
              <div className="bg-black/60 border border-white/10 px-2 py-1 flex items-center gap-2 text-[9px] font-mono text-white/50 uppercase tracking-widest w-max rounded">
                <Clock className="w-3 h-3 text-white/30" /> 延迟: {videoLatencyMs}ms
              </div>
            )}
          </div>
          
        </div>
      </div>

      {/* 2. 右侧专业战术面板 */}
      <div className="w-[400px] bg-black flex flex-col shrink-0 overflow-y-auto custom-scrollbar shadow-[-10px_0_30px_rgba(0,0,0,0.5)] z-20">
        
        {/* 面板 Header: 主开关 */}
        <div className="px-6 py-5 border-b border-white/20 flex items-center justify-between sticky top-0 bg-black/95 backdrop-blur z-20">
          <div className="flex items-center gap-4">
            <div className={`p-2.5 rounded border border-white/10 transition-colors ${safeStatus.enabled ? 'bg-white text-black' : 'bg-transparent text-white/40'}`}>
              <Shield className="w-5 h-5" />
            </div>
            <div>
              <h2 className="font-black text-white text-sm tracking-widest uppercase">驱离执勤系统</h2>
              <p className="text-[9px] text-white/40 font-mono mt-0.5 tracking-tighter">GUARD_SERVICE_ONLINE</p>
            </div>
          </div>
          
          <button 
            onClick={onToggleEnable}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${safeStatus.enabled ? 'bg-white' : 'bg-zinc-800 border border-white/20'}`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full transition-transform ${safeStatus.enabled ? 'translate-x-6 bg-black' : 'translate-x-1 bg-zinc-500'}`} />
          </button>
        </div>

        <div className="p-6 space-y-8 flex-1">
          
          {/* 核心状态卡片 */}
          <section>
            <h3 className="text-[10px] font-black text-white/40 mb-3 tracking-widest uppercase flex justify-between items-center">
              <span>状态监测</span>
            </h3>
            <div className={`relative overflow-hidden rounded bg-black border p-6 flex flex-col items-center justify-center gap-3 transition-colors ${currentStateInfo.border}`}>
               <div className={`absolute inset-0 opacity-10 pointer-events-none ${currentStateInfo.bg.replace('/10', '')}`} />
               <currentStateInfo.icon className={`w-10 h-10 ${currentStateInfo.color} relative z-10 ${currentStateInfo.pulse ? 'animate-pulse' : ''}`} />
               <div className="text-center relative z-10">
                 <h2 className={`text-xl font-black tracking-widest ${currentStateInfo.color} drop-shadow-lg ${!safeStatus.enabled && 'opacity-50'}`}>
                   {safeStatus.enabled ? currentStateInfo.label : '系统未启用'}
                 </h2>
                 <p className="text-[10px] text-white/50 mt-1 uppercase tracking-widest font-bold">{safeStatus.enabled ? currentStateInfo.desc : '请打开右上角主开关'}</p>
               </div>
            </div>

            {/* 一键急停按钮 */}
            {safeStatus.enabled && (
              <button
                onClick={onEmergencyStop}
                className="mt-4 w-full py-3.5 bg-red-600/10 border border-red-600/50 hover:bg-red-600/30 hover:border-red-500 text-red-500 font-black tracking-widest uppercase rounded flex items-center justify-center gap-2 transition-all active:scale-95 text-xs shadow-[0_0_15px_rgba(220,38,38,0.1)] hover:shadow-[0_0_20px_rgba(220,38,38,0.3)]"
              >
                <Octagon className="w-4 h-4" />
                急停终止 E-STOP
              </button>
            )}

            {/* 音频播放按钮 */}
            <button
              onClick={onAudioToggle}
              className={`mt-3 w-full py-3 border font-black tracking-widest uppercase rounded flex items-center justify-center gap-2 transition-all active:scale-95 text-xs ${
                isAudioPlaying
                  ? 'bg-amber-500/20 border-amber-500/60 hover:bg-amber-500/30 hover:border-amber-400 text-amber-400 shadow-[0_0_12px_rgba(245,158,11,0.15)]'
                  : 'bg-zinc-900 border-white/20 hover:border-white/50 hover:bg-zinc-800 text-white/60 hover:text-white'
              }`}
            >
              {isAudioPlaying ? <Volume2 className="w-4 h-4 animate-pulse" /> : <VolumeX className="w-4 h-4" />}
              {isAudioPlaying ? '停止音频' : '播放音频'}
            </button>
          </section>

          {/* 战术数据监控 */}
          <section className="space-y-4">
            <h3 className="text-[10px] font-black text-white/40 tracking-widest uppercase">战术指标</h3>
            
            <div className="bg-zinc-950 border border-white/10 rounded p-5 space-y-6">
              
              {/* 区域识别质量槽 */}
              <div className="space-y-3">
                <div className="flex justify-between items-end">
                  <span className="text-[10px] text-white/60 font-black uppercase tracking-widest flex items-center gap-2">
                    <Crosshair className="w-3.5 h-3.5 text-white/30" /> 识别质量
                  </span>
                  <span className={`font-mono text-sm font-black ${getQualityColor(safeStatus.zone_quality).split(' ')[0]}`}>
                    {(safeStatus.zone_quality * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="h-2 w-full bg-black rounded overflow-hidden border border-white/10 relative">
                  <div className="absolute left-[30%] top-0 bottom-0 w-px bg-red-500/50 z-10" title="可接受底线 30%"></div>
                  <div className="absolute left-[70%] top-0 bottom-0 w-px bg-emerald-500/50 z-10" title="优良阈值 70%"></div>
                  <div 
                    className={`h-full transition-all duration-300 ease-out ${getQualityColor(safeStatus.zone_quality).split(' ')[1]}`}
                    style={{ width: `${Math.max(0, Math.min(100, safeStatus.zone_quality * 100))}%` }}
                  />
                </div>
                
                {/* 区域丢失帧数监控 */}
                <div className="pt-2 flex justify-between items-center text-[10px] text-white/40 font-black uppercase tracking-widest">
                  <span className="flex items-center gap-1.5"><AlertTriangle className={`w-3.5 h-3.5 ${safeStatus.zone_lost_frames > 15 ? 'text-orange-500 animate-pulse' : 'text-white/30'}`} /> 丢失监控</span>
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 bg-black border border-white/5 overflow-hidden">
                      <div 
                        className={`h-full transition-all duration-100 ${safeStatus.zone_lost_frames > 15 ? 'bg-orange-500 shadow-[0_0_5px_orange]' : 'bg-white/30'}`}
                        style={{ width: `${Math.min(100, (safeStatus.zone_lost_frames / 30) * 100)}%` }}
                      />
                    </div>
                    <span className="font-mono w-6 text-right text-white/60">{safeStatus.zone_lost_frames}/30</span>
                  </div>
                </div>
              </div>

              <div className="w-full h-px bg-white/5"></div>

              {/* 动作进度槽 */}
              <div className="grid grid-cols-2 gap-5">
                <div className="space-y-2">
                  <div className="flex justify-between text-[10px] text-white/40 font-black uppercase tracking-widest">
                    <span>入侵判定</span>
                    <span className="font-mono text-white/60">{safeStatus.intrusion_counter}/{safeStatus.confirm_frames}</span>
                  </div>
                  <div className="h-1 w-full bg-black border border-white/5 overflow-hidden">
                    <div 
                      className={`h-full transition-all duration-75 ${safeStatus.intrusion_counter > 0 ? 'bg-red-500 shadow-[0_0_8px_red]' : 'bg-transparent'}`}
                      style={{ width: `${safeStatus.confirm_frames > 0 ? (safeStatus.intrusion_counter / safeStatus.confirm_frames) * 100 : 0}%` }}
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <div className="flex justify-between text-[10px] text-white/40 font-black uppercase tracking-widest">
                    <span>清空判定</span>
                    <span className="font-mono text-white/60">{safeStatus.clear_counter}/{safeStatus.clear_frames}</span>
                  </div>
                  <div className="h-1 w-full bg-black border border-white/5 overflow-hidden">
                    <div 
                      className={`h-full transition-all duration-75 ${safeStatus.clear_counter > 0 ? 'bg-blue-500 shadow-[0_0_8px_blue]' : 'bg-transparent'}`}
                      style={{ width: `${safeStatus.clear_frames > 0 ? (safeStatus.clear_counter / safeStatus.clear_frames) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              </div>

            </div>
          </section>

          {/* 快捷参数 */}
          <section className="space-y-4">
            <h3 className="text-[10px] font-black text-white/40 tracking-widest uppercase flex items-center gap-2">
              <Settings className="w-3.5 h-3.5 text-white/30" /> 参数概览
            </h3>
            
            <div className="grid grid-cols-3 gap-3">
               <div className="bg-zinc-950 border border-white/10 rounded px-3 py-2.5 flex flex-col justify-between">
                 <span className="text-[9px] text-white/40 mb-1 font-black uppercase tracking-widest">单次驱离</span>
                 <span className="text-[11px] font-mono text-white font-bold">{safeStatus.guard_duration_s.toFixed(1)}s</span>
               </div>
               <div className="bg-zinc-950 border border-white/10 rounded px-3 py-2.5 flex flex-col justify-between">
                 <span className="text-[9px] text-white/40 mb-1 font-black uppercase tracking-widest">最长限制</span>
                 <span className="text-[11px] font-mono text-white/70 font-bold">120.0s</span>
               </div>
               <div className="bg-zinc-950 border border-white/10 rounded px-3 py-2.5 flex flex-col justify-between">
                 <span className="text-[9px] text-white/40 mb-1 font-black uppercase tracking-widest">稳定阈值</span>
                 <span className="text-[11px] font-mono text-white/70 font-bold">15 帧</span>
               </div>
            </div>
          </section>

          {/* 区域坐标监控 */}
          <section className="space-y-3">
            <h3 className="text-[10px] font-black text-white/40 tracking-widest uppercase flex items-center gap-2">
              <Crosshair className="w-3.5 h-3.5 text-white/30" /> 区域坐标
            </h3>
            <div className="bg-zinc-950 border border-white/10 rounded p-4 font-mono text-[11px] space-y-3">
              {/* 起始坐标 */}
              <div className="space-y-1">
                <div className="text-[9px] text-white/40 font-black uppercase tracking-widest">起始区域（驱离开始时记录）</div>
                {safeStatus.start_zone_bbox ? (
                  <div className="grid grid-cols-4 gap-2">
                    {(['X', 'Y', 'W', 'H'] as const).map((label, i) => (
                      <div key={label} className="bg-black border border-amber-500/30 rounded px-2 py-1.5 flex flex-col items-center">
                        <span className="text-[8px] text-amber-500/60 font-black uppercase">{label}</span>
                        <span className="text-amber-400 font-bold text-xs">{safeStatus.start_zone_bbox![i]}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-white/20 text-[10px] italic">尚未记录（驱离开始后生效）</div>
                )}
              </div>
              {/* 当前坐标 */}
              <div className="space-y-1">
                <div className="text-[9px] text-white/40 font-black uppercase tracking-widest">当前区域（实时）</div>
                {safeStatus.current_zone_bbox ? (
                  <div className="grid grid-cols-4 gap-2">
                    {(['X', 'Y', 'W', 'H'] as const).map((label, i) => (
                      <div key={label} className="bg-black border border-emerald-500/30 rounded px-2 py-1.5 flex flex-col items-center">
                        <span className="text-[8px] text-emerald-500/60 font-black uppercase">{label}</span>
                        <span className="text-emerald-400 font-bold text-xs">{safeStatus.current_zone_bbox![i]}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-white/20 text-[10px] italic">未检测到区域</div>
                )}
              </div>
              {/* 面积对比（仅在驱离或返航时显示）*/}
              {safeStatus.start_zone_bbox && safeStatus.current_zone_bbox && (
                <div className="pt-1 border-t border-white/5 text-[10px] text-white/40 flex justify-between">
                  <span>面积比 (当前/起始)</span>
                  <span className="font-bold text-white/70">
                    {(
                      (safeStatus.current_zone_bbox[2] * safeStatus.current_zone_bbox[3]) /
                      (safeStatus.start_zone_bbox[2] * safeStatus.start_zone_bbox[3])
                    ).toFixed(2)}x
                  </span>
                </div>
              )}
            </div>
          </section>

        </div>
        <div className="h-56 border-t border-white/20 bg-zinc-950 flex flex-col shrink-0">
          <div className="px-4 py-3 border-b border-white/10 flex items-center gap-2 bg-black">
            <Terminal className="w-3.5 h-3.5 text-white/30" />
            <span className="text-[10px] font-black tracking-widest uppercase text-white/60">战术事件日志</span>
          </div>
          <div className="flex-1 overflow-y-auto p-4 font-mono text-[10px] custom-scrollbar bg-black/40">
            {guardLogs.length === 0 ? (
              <span className="text-white/20 italic font-sans text-xs">等待监控事件...</span>
            ) : (
              guardLogs.map((log, index) => (
                <div key={`${log.timestamp}-${index}`} className="flex items-start gap-3 mb-2.5 border-b border-white/[0.05] pb-1.5 last:border-0 last:mb-0">
                  <span className="text-white/30 shrink-0">[{new Date(log.timestamp * 1000).toLocaleTimeString([], { hour12: false, minute: '2-digit', second: '2-digit' })}]</span>
                  <span className={`leading-relaxed font-bold break-all ${
                    log.level === 'error' ? 'text-red-400' :
                    log.level === 'warning' ? 'text-orange-400 flex-1' :
                    'text-white/70 flex-1'
                  }`}>
                    {log.message}
                  </span>
                </div>
              ))
            )}
            <div ref={logsEndRef} />
          </div>
        </div>

      </div>
    </div>
  );
}
