/**
 * 事件 WebSocket 连接管理。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getWsUrl } from '../config/api';
import type { AlertEvent, AIStatus, EventWebSocketStatus, AutoTrackStatus } from '../types/event';
import type { TrackDecision } from './useAutoTrack';
import type { TrackOverlayData } from '../components/TrackOverlay1';
import { ALERT_LATEST_DISPLAY_MS, mergeAlertEvent, parseAlertEvent } from './alertEventPolicy';
import { mergePoseOverlay, type PoseOverlayPayload } from './poseOverlayPolicy';
import { recordAlertReceived } from './alertReceipt';
import { expirePackageObservation, hasPackageObservation, isPackageUpdate, mergePackageObservation,
  observationAt, reconcilePackageAlert, PACKAGE_OBSERVATION_TTL_MS, type PackageAlertLink } from './packageOverlayObservation';

export interface EventHookState {
  status: EventWebSocketStatus;
  alerts: AlertEvent[];
  latestAlert: AlertEvent | null;
  aiStatus: AIStatus | null;
  autoTrackStatus: AutoTrackStatus | null;
  trackDecision: TrackDecision | null;
  trackOverlay: TrackOverlayData | null;
  connect: () => void;
  disconnect: () => void;
  acknowledgeLatestAlert: () => void;
  clearAlerts: () => void;
}

export function useEventWebSocket(): EventHookState {
  const [status, setStatus] = useState<EventWebSocketStatus>({
    status: 'disconnected',
    error: null,
  });
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [latestAlert, setLatestAlert] = useState<AlertEvent | null>(null);
  const [aiStatus, setAiStatus] = useState<AIStatus | null>(null);
  const [autoTrackStatus, setAutoTrackStatus] = useState<AutoTrackStatus | null>(null);
  const [trackDecision, setTrackDecision] = useState<TrackDecision | null>(null);
  const [trackOverlay, setTrackOverlay] = useState<TrackOverlayData | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const connectionIdRef = useRef(0);
  const connectRef = useRef<() => void>(() => {});
  const weatherRefreshSentRef = useRef(false);
  const packageAlertLinkRef = useRef<PackageAlertLink | null>(null);

  const connect = useCallback(() => {
    const rs = wsRef.current?.readyState;
    if (rs === WebSocket.OPEN || rs === WebSocket.CONNECTING) {
      return;
    }

    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
      wsRef.current.close(1000);
      wsRef.current = null;
    }

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    connectionIdRef.current += 1;
    const currentConnectionId = connectionIdRef.current;

    try {
      const ws = new WebSocket(getWsUrl('/ws/event'));
      wsRef.current = ws;
      setStatus({ status: 'connecting', error: null });

      ws.onopen = () => {
        if (currentConnectionId !== connectionIdRef.current) {
          return;
        }
        setStatus({ status: 'connected', error: null });
        reconnectAttemptsRef.current = 0;
        if (!weatherRefreshSentRef.current && window.location.pathname === '/') {
          ws.send(JSON.stringify({ msg_type: 'WEATHER_REFRESH' }));
          weatherRefreshSentRef.current = true;
        }
      };

      ws.onmessage = (event) => {
        const receivedAt = performance.now();
        const pageVisible = document.visibilityState === 'visible';
        if (currentConnectionId !== connectionIdRef.current) {
          return;
        }
        try {
          const message = JSON.parse(event.data) as { msg_type: string; timestamp: string; payload: Record<string, unknown> };

          if (message.msg_type === 'AI_STATUS' && message.payload) {
            setAiStatus(message.payload as unknown as AIStatus);
            return;
          }

          if (message.msg_type === 'AUTO_TRACK_STATUS' && message.payload) {
            setAutoTrackStatus(message.payload as unknown as AutoTrackStatus);
            return;
          }

          if (message.msg_type === 'TRACK_DECISION' && message.payload) {
            setTrackDecision(message.payload as unknown as TrackDecision);
            return;
          }

          if (message.msg_type === 'TRACK_OVERLAY' && message.payload) {
            const payload = message.payload as unknown as TrackOverlayData;
            setTrackOverlay((previous) => {
              const sameSize = previous?.frame_w === payload.frame_w && previous?.frame_h === payload.frame_h;
              const observedAt = observationAt(receivedAt, payload.frame_age_ms);
              return mergePackageObservation(previous, {
                ...payload,
                frame_received_at_monotonic: payload.frame_received_at_monotonic ?? previous?.frame_received_at_monotonic,
                poses: sameSize ? previous?.poses : undefined,
                active_actions: sameSize ? previous?.active_actions : undefined,
                keypoint_confidence: sameSize ? previous?.keypoint_confidence : undefined,
                pose_received_at_ms: sameSize ? previous?.pose_received_at_ms : undefined,
                pose_frame_received_at_monotonic: sameSize ? previous?.pose_frame_received_at_monotonic : undefined,
                person_received_at_ms: observedAt,
                person_frame_received_at_monotonic: payload.frame_received_at_monotonic,
                received_at_ms: receivedAt,
                tracking_received_at_ms: observedAt,
              }, 'TRACK_OVERLAY', receivedAt, payload);
            });
            return;
          }

          if (message.msg_type === 'POSE_OVERLAY' && message.payload) {
            const payload = message.payload as unknown as PoseOverlayPayload;
            setTrackOverlay((previous) => {
              const merged = mergePoseOverlay(previous, payload, receivedAt);
              // Layers have independent ordering: a valid authoritative package
              // can arrive after a newer person stage, without regressing people.
              if (merged === previous && !isPackageUpdate(payload, 'POSE_OVERLAY')) return previous;
              return mergePackageObservation(previous, merged, 'POSE_OVERLAY', receivedAt, payload);
            });
            return;
          }

          const alert = parseAlertEvent(message);
          if (!alert) return;
          if (alert.evidence_id && alert.timing) {
            alert.receipt_observation = recordAlertReceived(alert.evidence_id, receivedAt, pageVisible);
          }

          setLatestAlert(alert);
          setAlerts((prev) => mergeAlertEvent(prev, alert));
        } catch (error) {
          console.error('解析事件消息失败:', error);
        }
      };

      ws.onerror = () => {
        if (currentConnectionId !== connectionIdRef.current) {
          return;
        }
        setStatus({ status: 'error', error: 'WebSocket error' });
      };

      ws.onclose = (event) => {
        if (currentConnectionId !== connectionIdRef.current) {
          return;
        }
        setStatus({ status: 'disconnected', error: event.reason || null });
        packageAlertLinkRef.current = null;
        setTrackOverlay(null);

        if (event.code === 1000) {
          return;
        }

        if (reconnectAttemptsRef.current < 10) {
          reconnectAttemptsRef.current += 1;
          const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current - 1), 10000);
          reconnectTimeoutRef.current = window.setTimeout(() => {
            connectRef.current();
          }, delay);
        }
      };
    } catch (error) {
      console.error('创建事件 WebSocket 失败:', error);
      setStatus({ status: 'error', error: 'create failed' });
    }
  }, []);

  useEffect(() => {
    if (!latestAlert) {
      packageAlertLinkRef.current = null;
      return;
    }
    const result = reconcilePackageAlert(latestAlert, packageAlertLinkRef.current, trackOverlay, performance.now());
    packageAlertLinkRef.current = result.link;
    if (result.overlapping) {
      // Only dismiss this currently associated popup. Evidence/history is intact.
      setLatestAlert(current => current === latestAlert ? null : current);
    }
  }, [latestAlert, trackOverlay]);

  useEffect(() => {
    const observedAt = trackOverlay?.package_received_at_ms;
    if (observedAt === undefined || !hasPackageObservation(trackOverlay)) return;
    const delay = Math.max(0, Math.ceil(observedAt + PACKAGE_OBSERVATION_TTL_MS - performance.now())) + 1;
    const timer = window.setTimeout(() => {
      setTrackOverlay((current) => current ? expirePackageObservation(current, performance.now()) : current);
    }, delay);
    return () => window.clearTimeout(timer);
  }, [trackOverlay]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    if (!latestAlert) return;
    const currentAlert = latestAlert;
    const timer = window.setTimeout(() => {
      setLatestAlert((value) => value === currentAlert ? null : value);
    }, ALERT_LATEST_DISPLAY_MS);
    return () => window.clearTimeout(timer);
  }, [latestAlert]);

  const acknowledgeLatestAlert = useCallback(() => {
    setLatestAlert(null);
  }, []);

  const clearAlerts = useCallback(() => {
    setAlerts([]);
    setLatestAlert(null);
  }, []);

  const disconnect = useCallback(() => {
    connectionIdRef.current += 1;
    packageAlertLinkRef.current = null;
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close(1000);
      wsRef.current = null;
    }
    setTrackOverlay(null);
    setStatus({ status: 'disconnected', error: null });
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(connect, 0);
    return () => {
      window.clearTimeout(timer);
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    status,
    alerts,
    latestAlert,
    aiStatus,
    autoTrackStatus,
    trackDecision,
    trackOverlay,
    connect,
    disconnect,
    acknowledgeLatestAlert,
    clearAlerts,
  };
}
