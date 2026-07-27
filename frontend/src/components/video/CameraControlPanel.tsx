import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Crosshair,
  Lock,
  Minus,
  Plus,
  X,
} from 'lucide-react';
import { apiFetch } from '../../api/apiFetch';

type GimbalMode = 'angle' | 'head_lock' | 'head_follow' | 'fpv';

export interface GimbalStatus {
  connected: boolean;
  timestamp?: string | null;
  error?: string | null;
  mode: string;
  mode_code: number;
  relative_roll_deg: number;
  relative_pitch_deg: number;
  relative_yaw_deg: number;
  absolute_roll_deg: number;
  absolute_pitch_deg: number;
  absolute_yaw_deg: number;
  angular_velocity_roll_dps: number;
  angular_velocity_pitch_dps: number;
  angular_velocity_yaw_dps: number;
  zoom_ratio: number | null;
  picture_mode: string;
  picture_mode_code: number;
  osd_enabled: boolean;
  night_vision_enabled: boolean;
  lighting_enabled: boolean;
  digital_zoom_enabled: boolean;
  camera_recording: boolean;
  hardware_version: number | null;
  firmware_version: number | null;
  pod_code: number | null;
  error_code: number | null;
}

interface Props {
  open: boolean;
  onClose: () => void;
}

const modeLabels: Record<string, string> = {
  angle: '角度控制',
  head_lock: '机头锁定',
  head_follow: '机头跟随',
  fpv: 'FPV',
  orthoview: '垂直俯视',
  euler: '欧拉角控制',
  gaze: '凝视',
  track: '云台跟踪',
  unknown: '未知',
};

const pictureModeLabels: Record<string, string> = {
  visible: '可见光',
  thermal: '热成像',
  visible_thermal_pip: '可见光＋热成像窗',
  thermal_visible_pip: '热成像＋可见光窗',
};

const actionButton =
  'h-9 min-w-9 rounded-lg border border-white/15 bg-white/[0.04] text-slate-200 hover:border-cyan-300/60 hover:bg-cyan-300/10 hover:text-cyan-100 disabled:cursor-not-allowed disabled:opacity-30 transition-all';

export function CameraControlPanel({ open, onClose }: Props) {
  const [status, setStatus] = useState<GimbalStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [targetPitch, setTargetPitch] = useState(0);
  const [targetYaw, setTargetYaw] = useState(0);
  const initializedRef = useRef(false);

  const updateFromStatus = useCallback((next: GimbalStatus) => {
    setStatus(next);
    if (!next.connected) {
      setError(next.error || '云台未连接');
      return;
    }
    setError(null);
    if (!initializedRef.current) {
      setTargetPitch(Math.max(-90, Math.min(30, Math.round(next.relative_pitch_deg))));
      setTargetYaw(Math.max(-170, Math.min(170, Math.round(next.relative_yaw_deg))));
      initializedRef.current = true;
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      updateFromStatus(await apiFetch<GimbalStatus>('/api/v1/gimbal/status'));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [updateFromStatus]);

  useEffect(() => {
    if (!open) {
      initializedRef.current = false;
      return;
    }
    void refreshStatus();
    const timer = window.setInterval(() => void refreshStatus(), 1000);
    return () => window.clearInterval(timer);
  }, [open, refreshStatus]);

  const runAction = useCallback(async (
    name: string,
    path: string,
    body?: Record<string, unknown>,
    successMessage?: string,
  ) => {
    setBusy(name);
    setNotice(null);
    try {
      const next = await apiFetch<GimbalStatus>(path, {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      updateFromStatus(next);
      setNotice(successMessage || '设置已应用');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }, [updateFromStatus]);

  if (!open) return null;

  const controlsDisabled = busy !== null || !status?.connected;
  const setMode = (mode: GimbalMode) => runAction(
    `mode-${mode}`,
    '/api/v1/gimbal/mode',
    { mode },
    `已切换为${modeLabels[mode]}`,
  );
  const jog = (pitch: number, yaw: number) => runAction(
    `jog-${pitch}-${yaw}`,
    '/api/v1/gimbal/jog',
    { pitch_velocity_dps: pitch, yaw_velocity_dps: yaw },
    '点动完成',
  );
  const updateSettings = (
    name: string,
    values: Record<string, unknown>,
    message: string,
  ) => runAction(name, '/api/v1/gimbal/settings', values, message);

  return (
    <div className="absolute bottom-28 left-1/2 z-40 w-[min(760px,calc(100%-2rem))] -translate-x-1/2 overflow-hidden rounded-2xl border border-white/20 bg-[#07090d]/95 shadow-[0_28px_90px_rgba(0,0,0,0.75)] backdrop-blur-xl">
      <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
        <div className="flex items-center gap-3">
          <div className={`h-2.5 w-2.5 rounded-full ${status?.connected ? 'bg-emerald-400 shadow-[0_0_12px_#34d399]' : 'bg-red-500'}`} />
          <div>
            <div className="text-sm font-black tracking-wide text-white">Z2-Mini 相机调节</div>
            <div className="text-[10px] text-white/45">
              {status?.connected
                ? `${modeLabels[status.mode] || status.mode} · TCP 2332`
                : '正在连接云台控制器'}
            </div>
          </div>
        </div>
        <button type="button" onClick={onClose} className="rounded-lg p-2 text-white/50 hover:bg-white/10 hover:text-white" aria-label="关闭相机调节">
          <X size={18} />
        </button>
      </div>

      <div className="max-h-[min(62vh,560px)] overflow-y-auto p-4">
        {(error || notice) && (
          <div className={`mb-3 rounded-lg border px-3 py-2 text-xs ${
            error
              ? 'border-red-400/30 bg-red-400/10 text-red-200'
              : 'border-emerald-400/25 bg-emerald-400/10 text-emerald-200'
          }`}>
            {error || notice}
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-3">
          <AngleCard label="相对俯仰" value={status?.relative_pitch_deg} suffix="°" />
          <AngleCard label="相对偏航" value={status?.relative_yaw_deg} suffix="°" />
          <AngleCard
            label="当前变焦"
            value={status?.zoom_ratio ?? undefined}
            suffix={status?.zoom_ratio == null ? '--' : '×'}
          />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[220px_1fr]">
          <section className="rounded-xl border border-white/10 bg-white/[0.025] p-4">
            <div className="mb-3 text-[10px] font-black uppercase tracking-[0.2em] text-white/40">云台点动</div>
            <div className="mx-auto grid w-[132px] grid-cols-3 gap-2">
              <div />
              <button type="button" disabled={controlsDisabled} onClick={() => void jog(12, 0)} className={actionButton} title="向上点动">
                <ChevronUp className="mx-auto" size={20} />
              </button>
              <div />
              <button type="button" disabled={controlsDisabled} onClick={() => void jog(0, -12)} className={actionButton} title="向左点动">
                <ChevronLeft className="mx-auto" size={20} />
              </button>
              <button
                type="button"
                disabled={controlsDisabled}
                onClick={() => void runAction('center', '/api/v1/gimbal/center', undefined, '云台已回中')}
                className={`${actionButton} border-cyan-300/35 text-cyan-200`}
                title="云台回中"
              >
                <Crosshair className="mx-auto" size={18} />
              </button>
              <button type="button" disabled={controlsDisabled} onClick={() => void jog(0, 12)} className={actionButton} title="向右点动">
                <ChevronRight className="mx-auto" size={20} />
              </button>
              <div />
              <button type="button" disabled={controlsDisabled} onClick={() => void jog(-12, 0)} className={actionButton} title="向下点动">
                <ChevronDown className="mx-auto" size={20} />
              </button>
              <div />
            </div>
            <p className="mt-3 text-center text-[9px] leading-4 text-white/30">每次点动 0.45 秒，后端自动停止</p>
          </section>

          <section className="rounded-xl border border-white/10 bg-white/[0.025] p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="text-[10px] font-black uppercase tracking-[0.2em] text-white/40">指定角度</div>
              <span className="text-[9px] text-white/30">相对安装载体</span>
            </div>
            <AngleSlider
              label="俯仰"
              value={targetPitch}
              min={-90}
              max={30}
              onChange={setTargetPitch}
            />
            <AngleSlider
              label="偏航"
              value={targetYaw}
              min={-170}
              max={170}
              onChange={setTargetYaw}
            />
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={controlsDisabled}
                onClick={() => void runAction(
                  'position',
                  '/api/v1/gimbal/position',
                  { pitch_deg: targetPitch, yaw_deg: targetYaw },
                  `目标角度：俯仰 ${targetPitch}°，偏航 ${targetYaw}°`,
                )}
                className="rounded-lg bg-cyan-300 px-4 py-2 text-[10px] font-black text-slate-950 hover:bg-cyan-200 disabled:opacity-30"
              >
                应用角度
              </button>
              <PresetButton disabled={controlsDisabled} onClick={() => { setTargetPitch(0); setTargetYaw(0); }}>水平</PresetButton>
              <PresetButton disabled={controlsDisabled} onClick={() => { setTargetPitch(-45); setTargetYaw(0); }}>向下 45°</PresetButton>
            </div>
          </section>
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <section className="rounded-xl border border-white/10 bg-white/[0.025] p-4">
            <div className="mb-3 text-[10px] font-black uppercase tracking-[0.2em] text-white/40">稳定模式</div>
            <div className="grid grid-cols-3 gap-2">
              <ModeButton active={status?.mode === 'head_follow'} disabled={controlsDisabled} onClick={() => void setMode('head_follow')}>跟随</ModeButton>
              <ModeButton active={status?.mode === 'head_lock'} disabled={controlsDisabled} onClick={() => void setMode('head_lock')}>
                <Lock size={13} /> 锁定
              </ModeButton>
              <ModeButton active={status?.mode === 'fpv'} disabled={controlsDisabled} onClick={() => void setMode('fpv')}>FPV</ModeButton>
            </div>

            <div className="mt-4 text-[10px] font-black uppercase tracking-[0.2em] text-white/40">镜头</div>
            <div className="mt-2 flex gap-2">
              <button type="button" disabled={controlsDisabled} onClick={() => void runAction('zoom-out', '/api/v1/gimbal/zoom', { action: 'out' }, '变焦缩小')} className={`${actionButton} flex-1`}>
                <Minus className="mx-auto" size={18} />
              </button>
              <div className="flex flex-[1.6] items-center justify-center rounded-lg border border-white/10 bg-black/20 font-mono text-sm font-black text-cyan-100">
                {status?.zoom_ratio == null ? '--' : `${status.zoom_ratio.toFixed(1)}×`}
              </div>
              <button type="button" disabled={controlsDisabled} onClick={() => void runAction('zoom-in', '/api/v1/gimbal/zoom', { action: 'in' }, '变焦放大')} className={`${actionButton} flex-1`}>
                <Plus className="mx-auto" size={18} />
              </button>
            </div>
          </section>

          <section className="rounded-xl border border-white/10 bg-white/[0.025] p-4">
            <div className="mb-3 text-[10px] font-black uppercase tracking-[0.2em] text-white/40">画面设置</div>
            <div className="mb-3">
              <div className="grid grid-cols-2 gap-2">
                <ModeButton
                  active={status?.picture_mode === 'visible'}
                  disabled={controlsDisabled}
                  onClick={() => void runAction(
                    'picture-visible',
                    '/api/v1/gimbal/picture-mode',
                    { mode: 'visible' },
                    '已切换到可见光画面',
                  )}
                >
                  可见光
                </ModeButton>
                <ModeButton
                  active={status?.picture_mode === 'thermal'}
                  disabled={controlsDisabled}
                  onClick={() => void runAction(
                    'picture-thermal',
                    '/api/v1/gimbal/picture-mode',
                    { mode: 'thermal' },
                    '已切换到热成像画面',
                  )}
                >
                  热成像
                </ModeButton>
                <ModeButton
                  active={status?.picture_mode === 'visible_thermal_pip'}
                  disabled={controlsDisabled}
                  onClick={() => void runAction(
                    'picture-visible-thermal-pip',
                    '/api/v1/gimbal/picture-mode',
                    { mode: 'visible_thermal_pip' },
                    '已切换到可见光主画面＋热成像小窗',
                  )}
                >
                  可见光主＋热成像小窗
                </ModeButton>
                <ModeButton
                  active={status?.picture_mode === 'thermal_visible_pip'}
                  disabled={controlsDisabled}
                  onClick={() => void runAction(
                    'picture-thermal-visible-pip',
                    '/api/v1/gimbal/picture-mode',
                    { mode: 'thermal_visible_pip' },
                    '已切换到热成像主画面＋可见光小窗',
                  )}
                >
                  热成像主＋可见光小窗
                </ModeButton>
              </div>
            </div>
            <div className="grid grid-cols-[1fr_auto] items-center gap-2">
              <ToggleButton
                active={Boolean(status?.osd_enabled)}
                disabled={controlsDisabled}
                onClick={() => void updateSettings('osd', { osd_enabled: !status?.osd_enabled }, `相机 OSD 已${status?.osd_enabled ? '关闭' : '开启'}`)}
              >
                OSD
              </ToggleButton>
              <span className="rounded-md border border-white/10 px-2 py-1.5 text-[9px] text-white/35">
                设备变焦 {status?.digital_zoom_enabled ? '已启用' : '未启用'}
              </span>
            </div>

            <div className="mt-3 grid grid-cols-3 gap-2 text-center">
              <DeviceInfo label="设备" value={status?.pod_code === 52 ? 'Z2-Mini' : status?.pod_code?.toString() || '--'} />
              <DeviceInfo
                label="画面"
                value={status
                  ? pictureModeLabels[status.picture_mode] || `模式 ${status.picture_mode_code}`
                  : '--'}
              />
              <DeviceInfo label="固件 / 硬件" value={`${status?.firmware_version ?? '--'} / ${status?.hardware_version ?? '--'}`} />
            </div>
          </section>
        </div>

        <div className="mt-3 flex items-center justify-between text-[9px] text-white/25">
          <span>相对横滚 {status?.relative_roll_deg?.toFixed(2) ?? '--'}° · 绝对航向 {status?.absolute_yaw_deg?.toFixed(2) ?? '--'}°</span>
          <span>{busy ? '正在执行命令…' : '控制命令已启用超时保护'}</span>
        </div>
      </div>
    </div>
  );
}

function AngleCard({ label, value, suffix }: { label: string; value?: number; suffix: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.025] px-4 py-3">
      <div className="text-[9px] font-bold uppercase tracking-widest text-white/35">{label}</div>
      <div className="mt-1 font-mono text-xl font-black text-cyan-100">
        {value == null ? '--' : value.toFixed(2)}
        <span className="ml-1 text-xs text-cyan-100/50">{suffix}</span>
      </div>
    </div>
  );
}

function AngleSlider({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="mb-2 grid grid-cols-[38px_1fr_44px] items-center gap-3">
      <span className="text-[10px] text-white/45">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={1}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="min-w-0 accent-cyan-300"
      />
      <span className="text-right font-mono text-xs font-bold text-cyan-100">{value}°</span>
    </label>
  );
}

function PresetButton({ disabled, onClick, children }: { disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" disabled={disabled} onClick={onClick} className="rounded-lg border border-white/15 px-3 py-2 text-[9px] font-bold text-white/60 hover:border-white/35 hover:text-white disabled:opacity-30">
      {children}
    </button>
  );
}

function ModeButton({ active, disabled, onClick, children }: { active: boolean; disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" disabled={disabled} onClick={onClick} className={`flex items-center justify-center gap-1 rounded-lg border px-2 py-2 text-[9px] font-black transition-all disabled:opacity-30 ${active ? 'border-cyan-300/60 bg-cyan-300/15 text-cyan-100' : 'border-white/10 text-white/50 hover:border-white/30 hover:text-white'}`}>
      {children}
    </button>
  );
}

function ToggleButton({ active, disabled, onClick, children }: { active: boolean; disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" disabled={disabled} onClick={onClick} className={`rounded-lg border px-3 py-2 text-[9px] font-black transition-all disabled:opacity-30 ${active ? 'border-emerald-300/50 bg-emerald-300/12 text-emerald-100' : 'border-white/10 text-white/45 hover:border-white/30 hover:text-white'}`}>
      {children} · {active ? '开' : '关'}
    </button>
  );
}

function DeviceInfo({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 px-2 py-2">
      <div className="text-[8px] uppercase tracking-wider text-white/25">{label}</div>
      <div className="mt-1 font-mono text-[10px] font-bold text-white/60">{value}</div>
    </div>
  );
}
