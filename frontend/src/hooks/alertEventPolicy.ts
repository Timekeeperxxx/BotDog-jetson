import type { AlertEvent } from '../types/event';

export const ALERT_MERGE_WINDOW_MS = 60_000;
export const ALERT_HISTORY_LIMIT = 10;

function alertMergeKey(alert: AlertEvent): string | null {
  const key = alert.event_code || alert.event_type;
  return key ? String(key) : null;
}

function timestampMs(alert: AlertEvent): number | null {
  const value = Date.parse(alert.timestamp);
  return Number.isFinite(value) ? value : null;
}

export function mergeAlertEvent(
  previous: AlertEvent[],
  incoming: AlertEvent,
  mergeWindowMs = ALERT_MERGE_WINDOW_MS,
): AlertEvent[] {
  const key = alertMergeKey(incoming);
  const incomingAt = timestampMs(incoming);
  const matchingIndex = previous.findIndex((item) => {
    if (!key || alertMergeKey(item) !== key) return false;
    const itemAt = timestampMs(item);
    return (
      incomingAt !== null
      && itemAt !== null
      && Math.abs(incomingAt - itemAt) <= mergeWindowMs
    );
  });

  if (matchingIndex < 0) {
    return [incoming, ...previous].slice(0, ALERT_HISTORY_LIMIT);
  }

  const matching = previous[matchingIndex];
  const merged: AlertEvent = {
    ...matching,
    ...incoming,
    first_timestamp: matching.first_timestamp ?? matching.timestamp,
    repeat_count: Math.max(1, Number(matching.repeat_count) || 1) + 1,
  };

  return [
    merged,
    ...previous.filter((_, index) => index !== matchingIndex),
  ].slice(0, ALERT_HISTORY_LIMIT);
}
