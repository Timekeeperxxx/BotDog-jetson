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

// 跟踪状态由状态面板消费；只有正式告警进入卡片列表。
export function parseAlertEvent(message: {
  msg_type: string; timestamp?: string; payload?: Record<string, unknown>;
}): AlertEvent | null {
  const payload = message.payload;
  if (message.msg_type !== 'ALERT_RAISED' || !payload) return null;
  const text = typeof payload.message === 'string' ? payload.message.trim() : '';
  const code = typeof payload.event_code === 'string' ? payload.event_code.trim() : '';
  if (!text && !code) return null;
  const severity = String(payload.severity ?? 'INFO').toUpperCase();
  return {
    ...payload,
    event_type: typeof payload.event_type === 'string' ? payload.event_type : '',
    event_code: code,
    message: text || '收到异常告警，请查看详情',
    severity: severity === 'CRITICAL' || severity === 'WARNING' ? severity : 'INFO',
    timestamp: message.timestamp || String(payload.timestamp || ''),
    confidence: typeof payload.confidence === 'number' && Number.isFinite(payload.confidence)
      ? Math.min(1, Math.max(0, payload.confidence)) : undefined,
    evidence_id: typeof payload.evidence_id === 'number' && Number.isInteger(payload.evidence_id)
      && payload.evidence_id > 0 ? payload.evidence_id : undefined,
  };
}

const alertTitles: Record<string, string> = {
  E_AI_PERSON: '检测到人员',
  E_AI_GUNS: '发现疑似枪械',
  E_AI_KNIFE: '发现疑似刀具',
  E_POSE_CLIMBING_SUSPECTED: '人员疑似攀爬',
  E_POSE_LYING: '人员疑似倒地',
  E_POSE_CROUCHING: '重点区域持续蹲伏',
  E_POSE_LOITERING: '重点区域长时间停留',
  E_FENCE_DWELL: '围栏附近停留',
  E_FENCE_CONTACT: '人员接触围栏',
  E_FENCE_CLIMBING_SUSPECTED: '人员疑似翻越围栏',
  NAV_PATH_BLOCKED: '道路持续受阻',
  NAV_SENSOR_LOST: '导航数据中断',
  NAV_BLOCK_CLEARED: '道路恢复畅通',
  NAV_AUTO_REGOAL: '已重试导航目标',
  FENCE_DETECTION_CONTROL_FAILED: '围栏检测操作失败',
  E_AUTO_TRACK_LOCKED: '已锁定跟踪目标',
  E_AUTO_TRACK_STOPPED: '跟踪结束，已抓拍',
  E_MANUAL_SNAPSHOT: '手动抓拍已保存',
};

export function alertSummary(alert: AlertEvent): string {
  if (alert.event_code === 'E_THERMAL_HIGH' && typeof alert.temperature === 'number') {
    return `目标温度过高：${alert.temperature.toFixed(1)}℃`;
  }
  if (alert.event_type === 'GUARD_MISSION_SNAPSHOT') return '驱离过程抓拍';
  return alertTitles[alert.event_code] || alert.message || '异常告警';
}
