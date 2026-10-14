import { useEffect, useRef, type RefObject } from 'react';
import { recordAlertDisplayed, recordLegacyAlertDisplayed, type AlertReceiptObservation } from './alertReceipt';

export function useAlertDisplayReceipt(ref: RefObject<HTMLElement | null>, evidenceId?: number,
  enabled = false, received?: AlertReceiptObservation) {
  const measurement = useRef<{ evidenceId: number; received?: AlertReceiptObservation; observation: AlertReceiptObservation } | undefined>(undefined);
  useEffect(() => {
    if (!enabled || !evidenceId || !ref.current) return;
    const mounted = performance.now();
    if (measurement.current?.evidenceId !== evidenceId || measurement.current.received !== received) {
      measurement.current = { evidenceId, received, observation: received ? { ...received } : {
        clientId: '', receivedAt: mounted, pageVisibleOnReceive: document.visibilityState === 'visible', visibilityWaitMs: 0,
      } };
    }
    const observation = measurement.current.observation;
    if (observation.displayedAt !== undefined) return;
    let first = 0, second = 0;
    const cardVisible = () => {
      const element = ref.current;
      if (!element) return false;
      const rect = element.getBoundingClientRect();
      let left = Math.max(0, rect.left), top = Math.max(0, rect.top);
      let right = Math.min(innerWidth, rect.right), bottom = Math.min(innerHeight, rect.bottom);
      // Include clipping by the scrolling alert list, not only the window.
      for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent), bounds = parent.getBoundingClientRect();
        if (bounds.width && /(auto|scroll|hidden|clip)/.test(style.overflowX)) { left = Math.max(left, bounds.left); right = Math.min(right, bounds.right); }
        if (bounds.height && /(auto|scroll|hidden|clip)/.test(style.overflowY)) { top = Math.max(top, bounds.top); bottom = Math.min(bottom, bounds.bottom); }
      }
      return right > left && bottom > top;
    };
    const visible = () => document.visibilityState === 'visible' && cardVisible();
    if (observation.mountedAt === undefined) {
      observation.mountedAt = mounted;
      observation.pageVisibleOnMount = document.visibilityState === 'visible';
      observation.cardVisibleOnMount = cardVisible();
      observation.waitingSince = mounted;
    }
    const pause = (now: number) => {
      observation.waitingSince ??= now;
      cancelAnimationFrame(first); cancelAnimationFrame(second);
      first = 0; second = 0;
    };
    const observe = () => {
      if (observation.displayedAt !== undefined) return;
      const now = performance.now();
      if (!visible()) { pause(now); return; }
      if (observation.waitingSince !== undefined) {
        observation.visibilityWaitMs += now - observation.waitingSince;
        observation.waitingSince = undefined;
      }
      observation.firstVisibleAt ??= now;
      if (first) return;
      first = requestAnimationFrame(() => {
        second = requestAnimationFrame(() => {
          first = 0; second = 0;
          if (observation.displayedAt !== undefined) return;
          if (!visible()) { pause(performance.now()); return; }
          observation.displayedAt = performance.now();
          if (received) recordAlertDisplayed(evidenceId, observation);
          else recordLegacyAlertDisplayed(evidenceId, observation.displayedAt);
        });
      });
    };
    const observer = typeof IntersectionObserver === 'undefined' ? undefined : new IntersectionObserver(observe);
    observer?.observe(ref.current);
    document.addEventListener('visibilitychange', observe);
    observe();
    return () => {
      if (observation.displayedAt === undefined) pause(performance.now());
      cancelAnimationFrame(first); cancelAnimationFrame(second);
      observer?.disconnect(); document.removeEventListener('visibilitychange', observe);
    };
  }, [ref, evidenceId, enabled, received]);
}
