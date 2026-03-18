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
  [key: string]: any;
}

export interface EventMessage {
  msg_type: string;
  timestamp: string;
  payload: AlertEvent;
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
}
