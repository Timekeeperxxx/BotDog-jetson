import { describe, expect, it } from 'vitest';
import type { AlertEvent } from '../types/event';
import { ALERT_HISTORY_LIMIT, mergeAlertEvent, alertSummary } from './alertEventPolicy';

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
  it('keeps vaulting and climbing as separate alert classes and titles', () => {
    const climb=alert('E_POSE_CLIMBING_SUSPECTED', '2026-10-06T05:00:00.000Z');
    const vault=alert('E_POSE_VAULTING_SUSPECTED', '2026-10-06T05:00:00.100Z');
    const merged=mergeAlertEvent([climb], vault);
    expect(merged).toHaveLength(2);
    expect(alertSummary(climb)).toBe('人员疑似攀爬');
    expect(alertSummary(vault)).toBe('人员疑似翻越');
  });
  it('merges the same alert class and retains the latest evidence', () => {
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

  it('keeps different classes separate and merges the same class even after 60 seconds', () => {
    const guns = alert('E_AI_GUNS', '2026-08-06T15:00:00.000Z');
    const knife = alert('E_AI_KNIFE', '2026-08-06T15:00:20.000Z');
    const laterGuns = alert('E_AI_GUNS', '2026-08-06T15:01:01.000Z');

    const withKnife = mergeAlertEvent([guns], knife);
    const result = mergeAlertEvent(withKnife, laterGuns);

    expect(result.map((item) => item.event_code)).toEqual([
      'E_AI_GUNS',
      'E_AI_KNIFE',
    ]);
    expect(result[0].repeat_count).toBe(2);
    expect(result[0].timestamp).toBe(laterGuns.timestamp);
    expect(result[1].repeat_count).toBeUndefined();
  });

  it('does not double-count duplicate evidence or replace newer details with an older alert', () => {
    const latest={...alert('E_POSE_VAULTING_SUSPECTED', '2026-10-06T05:20:00Z'), evidence_id: 20};
    const duplicate=mergeAlertEvent([latest], latest);
    expect(duplicate[0].repeat_count).toBe(1);
    const earlier={...alert('E_POSE_VAULTING_SUSPECTED', '2026-10-06T05:00:00Z'), evidence_id: 10};
    const merged=mergeAlertEvent(duplicate, earlier);
    expect(merged).toHaveLength(1);
    expect(merged[0].evidence_id).toBe(20);
    expect(merged[0].timestamp).toBe(latest.timestamp);
    expect(merged[0].first_timestamp).toBe(earlier.timestamp);
    expect(merged[0].repeat_count).toBe(2);
  });

  it('can still apply an explicitly requested finite merge window', () => {
    const first=alert('E_AI_GUNS', '2026-10-06T05:00:00Z');
    const later=alert('E_AI_GUNS', '2026-10-06T05:01:01Z');
    expect(mergeAlertEvent([first], later, 60_000)).toHaveLength(2);
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
