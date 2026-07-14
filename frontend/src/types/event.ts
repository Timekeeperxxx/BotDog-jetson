/**
 * 事件相关的类型定义
 */

// 使用 interface 导出，这是最兼容的方式
export interface AlertEvent {
  event_type: string;
  event_code: string;
  severity: 'INFO' | 'WARNING' | 'CRITICAL';
  message: string;
  evidence_id?: number;
  image_url?: string;
  gps?: {
    lat: number;
    lon: number;
  };
  confidence?: number;
  timestamp: string;
  temperature?: number;
  threshold?: number;
  [key: string]: unknown;
}

export interface EventMessage {
  msg_type: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface EventWebSocketStatus {
  status: 'disconnected' | 'connecting' | 'connected' | 'error';
  error: string | null;
}

export interface AIStatus {
  frames_processed: number;
  detections_count: number;
  mode: 'idle' | 'patrol' | 'suspect' | 'alert';
  hits: number;
  stable_hits: number;
  latest_frame_index?: number;
  last_processed_frame_index?: number;
  queued_frames_dropped?: number;
  stale_frames_dropped?: number;
  frame_age_ms?: number;
  processing_ms?: number;
  detect_ms?: number;
  postprocess_ms?: number;
  end_to_end_ms?: number;
  frame_timeout_reason?: string | null;
}

// ──── 自动跟踪相关类型 ────────────────────────────────────────────────────────

export type AutoTrackStateValue =
  | 'DISABLED'
  | 'IDLE'
  | 'DETECTING'
  | 'TARGET_LOCKED'
  | 'FOLLOWING'
  | 'LOST_SHORT'
  | 'OUT_OF_ZONE_PENDING'
  | 'MANUAL_OVERRIDE'
  | 'PAUSED'
  | 'STOPPED';

export interface ActiveTargetInfo {
  track_id: number;
  bbox: [number, number, number, number];
  anchor_point: [number, number];
  inside_zone: boolean;
  lost_count: number;
  out_of_zone_count: number;
}

export interface ArbiterStatus {
  owner: 'NONE' | 'AUTO_TRACK' | 'WEB_MANUAL' | 'REMOTE_CONTROLLER' | 'E_STOP';
  active_requesters: string[];
  can_auto_track: boolean;
}

export interface AutoTrackStatus {
  enabled: boolean;
  paused: boolean;
  state: AutoTrackStateValue;
  active_target: ActiveTargetInfo | null;
  stop_reason: string | null;
  last_command: string | null;
  frames_processed: number;
  hit_count: number;
  stable_hits_threshold: number;
  control_arbiter: ArbiterStatus;
  multi_target_mode: boolean;
  candidate_count: number;
}

export interface KnownTarget {
  track_id: number;
}
