import { describe, expect, it } from 'vitest';
import type { AlertEvent } from '../types/event';
import { ALERT_HISTORY_LIMIT, mergeAlertEvent } from './alertEventPolicy';

function alert(
  eventCode: string,
  timestamp: string,
  confidence = 0.7,
): AlertEvent {
  return {
    event_type: 'AI_DETECTION',
    event_code: eventCode,
    severity: 'CRITICAL',
    message: eventCode,
    confidence,
    timestamp,
  };
}

describe('mergeAlertEvent', () => {
  it('merges the same alert class inside the 60 second window', () => {
    const first = alert('E_AI_GUNS', '2026-08-06T15:48:12.000Z', 0.68);
    const second = alert('E_AI_GUNS', '2026-08-06T15:48:33.000Z', 0.71);

    const result = mergeAlertEvent([first], second);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      event_code: 'E_AI_GUNS',
      timestamp: second.timestamp,
      first_timestamp: first.timestamp,
      confidence: 0.71,
      repeat_count: 2,
    });
  });

  it('keeps different classes and alerts outside the merge window separate', () => {
    const guns = alert('E_AI_GUNS', '2026-08-06T15:00:00.000Z');
    const knife = alert('E_AI_KNIFE', '2026-08-06T15:00:20.000Z');
    const laterGuns = alert('E_AI_GUNS', '2026-08-06T15:01:01.000Z');

    const withKnife = mergeAlertEvent([guns], knife);
    const result = mergeAlertEvent(withKnife, laterGuns);

    expect(result.map((item) => item.event_code)).toEqual([
      'E_AI_GUNS',
      'E_AI_KNIFE',
      'E_AI_GUNS',
    ]);
    expect(result.every((item) => item.repeat_count === undefined)).toBe(true);
  });

  it('keeps only the most recent alert history entries', () => {
    const existing = Array.from({ length: ALERT_HISTORY_LIMIT }, (_, index) => (
      alert(`E_${index}`, `2026-08-06T15:00:${String(index).padStart(2, '0')}.000Z`)
    ));
    const newest = alert('E_NEW', '2026-08-06T15:01:00.000Z');

    const result = mergeAlertEvent(existing, newest);

    expect(result).toHaveLength(ALERT_HISTORY_LIMIT);
    expect(result[0].event_code).toBe('E_NEW');
    expect(result.some((item) => item.event_code === 'E_9')).toBe(false);
  });
});
