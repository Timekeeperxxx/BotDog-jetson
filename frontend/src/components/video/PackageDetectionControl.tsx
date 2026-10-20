import { useEffect, useId, useRef, useState } from 'react';
import { apiFetch } from '../../api/apiFetch';

type RuntimeInfo = {
  runtime_enabled?: unknown;
  runtime_value?: unknown;
  runtime_state?: unknown;
};
type PackageConfig = RuntimeInfo & { value?: unknown };
type ConfigResponse = { configs?: { package_enabled?: PackageConfig } };
type UpdateResponse = RuntimeInfo & {
  success?: boolean;
  config?: PackageConfig;
  runtime_apply?: RuntimeInfo & { applied?: boolean; message?: string };
};

function enabledValue(value: unknown): boolean {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (['true', '1', 'on', 'yes'].includes(normalized)) return true;
    if (['false', '0', 'off', 'no'].includes(normalized)) return false;
  }
  throw new Error('包检测运行状态未知');
}

function runtimeEnabled(...sources: Array<RuntimeInfo | undefined>): boolean | undefined {
  for (const source of sources) {
    if (source?.runtime_enabled !== undefined) return enabledValue(source.runtime_enabled);
    if (source?.runtime_value !== undefined) return enabledValue(source.runtime_value);
  }
  return undefined;
}

function runtimeState(...sources: Array<RuntimeInfo | undefined>): string | null {
  for (const source of sources) {
    if (source?.runtime_state === undefined || source.runtime_state === null) continue;
    if (typeof source.runtime_state !== 'string') throw new Error('包检测模型状态无效');
    return source.runtime_state.trim().toLowerCase() || null;
  }
  return null;
}

function failedState(state: string | null): boolean {
  return state === 'failed' || state === 'error';
}

function transitioningState(state: string | null): boolean {
  return state !== null && ['loading', 'initializing', 'starting', 'stopping'].includes(state);
}

export function PackageDetectionControl() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [state, setState] = useState<string | null>(null);
  const [pending, setPending] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const changing = useRef(false);
  const revision = useRef(0);
  const mounted = useRef(false);
  const statusId = useId();
  const busy = pending !== null;
  const transitioning = transitioningState(state);

  useEffect(() => {
    mounted.current = true;
    let active = true;
    let sequence = 0;
    const refresh = async () => {
      if (changing.current) return;
      const requestedRevision = revision.current;
      const request = ++sequence;
      const canApply = () => active && !changing.current
        && requestedRevision === revision.current && request === sequence;
      try {
        const result = await apiFetch<ConfigResponse>('/api/v1/config?category=ai');
        const setting = result.configs?.package_enabled;
        const actual = runtimeEnabled(setting);
        const modelState = runtimeState(setting);
        // The persisted config.value alone does not establish a running model.
        if (actual === undefined) throw new Error('无法读取包检测运行状态');
        if (canApply()) {
          setEnabled(actual);
          setState(modelState);
          setError(failedState(modelState) ? '包检测模型加载失败，请检查板端状态' : null);
        }
      } catch (reason) {
        if (canApply()) {
          setEnabled(null);
          setState(null);
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => {
      active = false;
      mounted.current = false;
      window.clearInterval(timer);
    };
  }, []);

  const toggle = async () => {
    if (enabled === null || changing.current || transitioning) return;
    const requested = !enabled;
    changing.current = true;
    revision.current += 1;
    setPending(requested);
    setError(null);
    let actual: boolean | undefined;
    try {
      const result = await apiFetch<UpdateResponse>('/api/v1/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'package_enabled', value: requested, reason: '视频面板包检测开关' }),
      });
      // Accept runtime fields at the response, runtime_apply or config level.
      actual = runtimeEnabled(result, result.runtime_apply, result.config);
      const modelState = runtimeState(result, result.runtime_apply, result.config);
      if (mounted.current) {
        if (actual !== undefined) setEnabled(actual);
        setState(modelState);
      }
      if (failedState(modelState)) {
        throw new Error(`包检测模型加载失败${result.runtime_apply?.message ? `：${result.runtime_apply.message}` : ''}`);
      }
      if (transitioningState(modelState)) {
        throw new Error('包检测模型仍在切换，尚未确认生效');
      }
      if (result.success !== true || result.runtime_apply?.applied !== true) {
        throw new Error(result.runtime_apply?.message || '包检测设置尚未生效');
      }
      // Weapon-compatible POST replies may contain only config.value. That is
      // trusted only after the worker has explicitly confirmed runtime_apply.
      const confirmed = actual ?? enabledValue(result.config?.value);
      if (confirmed !== requested) throw new Error('包检测板端实际状态与请求不一致');
      if (mounted.current) setEnabled(confirmed);
    } catch (reason) {
      if (mounted.current) {
        // A timeout or saved-only response cannot prove whether the model ran.
        // Wait for a fresh GET instead of presenting the requested value as fact.
        setEnabled(actual ?? null);
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      changing.current = false;
      if (mounted.current) setPending(null);
    }
  };

  const stateLabel = busy
    ? pending ? '正在开启，等待模型就绪…' : '正在关闭，等待板端确认…'
    : enabled === null
      ? error ? '状态未知 · 等待重新读取' : '正在读取板端状态…'
      : failedState(state)
        ? '模型加载失败'
        : transitioning
          ? '模型正在切换，等待板端就绪…'
          : error
            ? '切换未确认 · 请查看错误信息'
            : enabled ? '已开启 · 包裹检测与遗弃告警' : '已关闭 · 停止包检测和新告警';

  return (
    <div className="border-b border-white/10 pb-3">
      <button
        type="button"
        role="switch"
        aria-label="包裹检测与告警"
        aria-checked={enabled ?? undefined}
        aria-busy={busy || transitioning}
        aria-describedby={statusId}
        disabled={enabled === null || busy || transitioning}
        onClick={() => void toggle()}
        className="flex w-full items-center gap-3 rounded-lg border border-amber-300/25 bg-amber-300/[0.06] px-3 py-2 text-left disabled:opacity-50"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-[11px] font-black text-white">包裹检测与告警</span>
          <span id={statusId} className="block text-[9px] text-white/55">{stateLabel}</span>
          <span className="block text-[9px] text-white/45">画框显示由下方「包裹画框」控制</span>
        </span>
        <span aria-hidden="true" className={`relative h-5 w-9 shrink-0 rounded-full ${enabled === true ? 'bg-amber-300' : 'bg-white/15'}`}>
          <span className={`absolute left-0 top-0.5 h-4 w-4 rounded-full bg-black transition-transform ${enabled === null ? 'translate-x-[9px]' : enabled ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
        </span>
      </button>
      {error && <p role="alert" className="mt-2 text-[10px] text-red-300">{error}</p>}
    </div>
  );
}
