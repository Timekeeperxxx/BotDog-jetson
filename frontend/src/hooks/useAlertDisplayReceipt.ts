import { useEffect, type RefObject } from 'react';
import { apiFetch } from '../api/apiFetch';

let clock: { offset: number; uncertainty: number; sampled: number } | undefined;
let pendingClock: Promise<NonNullable<typeof clock>> | undefined;
async function calibratedClock() {
  if (clock && performance.now() - clock.sampled < 30000) return clock;
  if (!pendingClock) pendingClock = (async () => {
    const before = performance.now();
    const sample = await apiFetch<{ server_time: string }>('/api/v1/evidence/clock', { cache: 'no-store' });
    const after = performance.now();
    const server = Date.parse(sample.server_time);
    if (!Number.isFinite(server) || after - before > 20000) throw new Error('告警校时失败');
    clock = { offset: server - (before + after) / 2, uncertainty: (after - before) / 2 + 1, sampled: after };
    return clock;
  })().finally(() => { pendingClock = undefined; });
  return pendingClock;
}

// DOM 可见且经过两次动画帧后采样；是浏览器呈现近似值，并非显示器曝光测量。
export function useAlertDisplayReceipt(ref: RefObject<HTMLElement | null>, evidenceId?: number, enabled = false) {
  useEffect(() => {
    if (!enabled || !evidenceId || !ref.current) return;
    let first = 0, second = 0, sent = false;
    const visible = () => {
      const element = ref.current;
      if (!element || document.visibilityState !== 'visible') return false;
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
    };
    const observe = () => {
      if (sent || first || !visible()) return;
      first = requestAnimationFrame(() => {
        second = requestAnimationFrame(() => {
          first = 0;
          if (!visible()) return;
          sent = true;
          const displayed = performance.now();
          void calibratedClock().then((sample) => apiFetch(`/api/v1/evidence/${evidenceId}/displayed`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ displayed_at: new Date(displayed + sample.offset).toISOString(), clock_uncertainty_ms: sample.uncertainty }),
          })).catch((error) => { console.error('告警呈现回执未保存', evidenceId, error); });
        });
      });
    };
    const observer = typeof IntersectionObserver === 'undefined' ? undefined : new IntersectionObserver(observe);
    observer?.observe(ref.current);
    document.addEventListener('visibilitychange', observe);
    observe();
    return () => {
      cancelAnimationFrame(first); cancelAnimationFrame(second);
      observer?.disconnect(); document.removeEventListener('visibilitychange', observe);
    };
  }, [ref, evidenceId, enabled]);
}
