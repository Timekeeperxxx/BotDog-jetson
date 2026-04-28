import type { ReactNode } from 'react';
import { Battery, Wifi, Thermometer } from 'lucide-react';
import type { TelemetryData } from '../../hooks/useBotDogWebSocket';

function TopStatus({ icon, value, label }: { icon: ReactNode; value: string; label: string }) {
  return (
    <div className="flex items-center space-x-3">
      <div className="p-2 rounded-sm bg-zinc-900 text-white border border-white/10">
        {icon}
      </div>
      <div className="flex flex-col -space-y-1">
        <span className="text-[9px] uppercase font-black text-slate-500 tracking-tighter">{label}</span>
        <span className="text-[11px] font-mono font-black text-white">{value}</span>
      </div>
    </div>
  );
}

function DataPointHeader({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div className="flex items-baseline space-x-2 group">
      <span className="text-[9px] uppercase font-black text-slate-500 tracking-tighter group-hover:text-white">{label}</span>
      <span className="text-lg font-mono font-black text-white">{value}</span>
      <span className="text-[10px] font-mono font-bold text-slate-400">{unit}</span>
    </div>
  );
}

export interface TopHeaderProps {
  isUiFullscreen: boolean;
  isMissionRunning: boolean;
  telemetry: TelemetryData | null;
  isConnected: boolean;
  videoLatencyMs: number | null;
}

export function TopHeader({
  isUiFullscreen,
  isMissionRunning,
  telemetry,
  isConnected,
  videoLatencyMs,
}: TopHeaderProps) {
  if (isUiFullscreen) return null;

  return (
    <header className="h-12 bg-black backdrop-blur-md border-b border-white/20 flex items-center justify-between px-6 z-40">
      <div className="flex items-center space-x-6">
        <div className="flex items-center space-x-3">
          <span className="text-[11px] font-black text-white uppercase tracking-widest">BotDog</span>
          <div className="h-4 w-px bg-white/30" />
          <span className="text-[10px] font-mono text-slate-300 font-bold tracking-tight">V5.0-核心终端</span>
        </div>
        {isMissionRunning && (
          <div className="flex items-center space-x-2 px-2.5 py-1 bg-white rounded-sm border border-white shadow-[0_0_10px_rgba(255,255,255,0.2)]">
            <div className="w-1.5 h-1.5 bg-black rounded-full animate-pulse" />
            <span className="text-[9px] font-black text-black uppercase tracking-tighter">Active</span>
          </div>
        )}
      </div>
      <div className="flex items-center space-x-10">
        <div className="hidden lg:flex items-center space-x-8 pr-8 border-r border-white/20 font-bold">
          <DataPointHeader label="速度" value={telemetry?.position.groundspeed != null ? telemetry.position.groundspeed.toFixed(1) : '--'} unit="m/s" />
          <DataPointHeader label="航向" value={telemetry ? (telemetry.attitude.yaw || 0).toFixed(0) : '--'} unit="°" />
          <DataPointHeader label="延迟" value={videoLatencyMs !== null ? `${videoLatencyMs}` : '--'} unit="ms" />
        </div>
        <div className="flex items-center space-x-6">
          <TopStatus icon={<Wifi size={16} />} value={isConnected ? '在线' : '离线'} label="链路" />
          <TopStatus icon={<Battery size={16} />} value={telemetry?.battery_pct != null ? `${telemetry.battery_pct.toFixed(0)}%` : '--'} label="电量" />
          <TopStatus icon={<Thermometer size={16} />} value={telemetry?.core_temp_c != null ? `${telemetry.core_temp_c.toFixed(0)}°C` : '--'} label="温度" />
        </div>
        <div className="text-[11px] font-mono font-black text-white pl-6 border-l border-white/20">
          {new Date().toLocaleTimeString('zh-CN', { hour12: false })}
        </div>
      </div>
    </header>
  );
}
