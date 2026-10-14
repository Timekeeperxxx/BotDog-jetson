import { useEffect, useRef, useState } from 'react';
import { apiFetch } from '../../api/apiFetch';

type ConfigResponse = { configs: { weapon_enabled?: { value: boolean | string; runtime_value?: boolean } } };
type UpdateResponse = {
  success: boolean;
  config: { value: boolean | string };
  runtime_apply: { applied: boolean; message: string };
};

function enabledValue(value: boolean | string): boolean {
  if (typeof value === 'boolean') return value;
  if (['true', '1', 'on', 'yes'].includes(value.toLowerCase())) return true;
  if (['false', '0', 'off', 'no'].includes(value.toLowerCase())) return false;
  throw new Error('刀枪检测状态无效');
}

export function WeaponDetectionControl() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changing = useRef(false);
  const revision = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const refresh = async () => {
      if (changing.current) return;
      const requestedRevision = revision.current;
      try {
        const result = await apiFetch<ConfigResponse>('/api/v1/config?category=ai');
        const setting = result.configs.weapon_enabled;
        const value = setting?.runtime_value ?? setting?.value;
        if (value === undefined) throw new Error('无法读取刀枪检测状态');
        if (mounted.current && !changing.current && requestedRevision === revision.current) {
          setEnabled(enabledValue(value));
          setError(null);
        }
      } catch (reason) {
        if (mounted.current && !changing.current && requestedRevision === revision.current) {
          setEnabled(null);
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => { mounted.current = false; window.clearInterval(timer); };
  }, []);

  const toggle = async () => {
    if (enabled === null || changing.current) return;
    changing.current = true;
    revision.current += 1;
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<UpdateResponse>('/api/v1/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'weapon_enabled', value: !enabled, reason: '视频面板刀枪检测开关' }),
      });
      if (!result.success || !result.runtime_apply.applied) {
        throw new Error(result.runtime_apply.message || '刀枪检测设置未生效');
      }
      if (mounted.current) setEnabled(enabledValue(result.config.value));
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      changing.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  return (
    <div className="border-b border-white/10 pb-3">
      <button
        type="button"
        role="switch"
        aria-label="刀枪检测与告警"
        aria-checked={enabled === true}
        disabled={enabled === null || busy}
        onClick={() => void toggle()}
        className="flex w-full items-center gap-3 rounded-lg border border-rose-300/25 bg-rose-300/[0.06] px-3 py-2 text-left disabled:opacity-50"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-[11px] font-black text-white">刀枪检测与告警</span>
          <span className="block text-[9px] text-white/55">
            {busy ? '正在应用到板端…' : enabled === null ? '正在读取板端状态…' : enabled ? '已开启 · 关闭后停止检测和新告警' : '已关闭 · 不产生新的刀枪告警'}
          </span>
        </span>
        <span className={`relative h-5 w-9 shrink-0 rounded-full ${enabled ? 'bg-rose-300' : 'bg-white/15'}`}>
          <span className={`absolute left-0 top-0.5 h-4 w-4 rounded-full bg-black transition-transform ${enabled ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
        </span>
      </button>
      {error && <p role="alert" className="mt-2 text-[10px] text-red-300">{error}</p>}
    </div>
  );
}
