/**
 * 视频流相关类型定义。
 *
 * 职责边界：
 * - 定义 WebRTC 信令消息类型
 * - 定义视频流状态类型
 * - 提供类型安全的视频数据访问
 */

/**
 * WebRTC 信令消息类型
 */
export type WebRTCSignalingMessageType = "offer" | "answer" | "ice_candidate" | "welcome" | "ice_candidates" | "error";

/**
 * ICE 候选
 */
export interface ICECandidate {
  candidate: string;
  sdpMid: string | null;
  sdpMLineIndex: number | null;
}

/**
 * SDP 内容
 */
export interface SDPContent {
  sdp: string;
  type: "offer" | "answer";
}

/**
 * WebRTC 信令消息
 */
export interface WebRTCSignalingMessage {
  msg_type: WebRTCSignalingMessageType;
  client_id?: string;
  payload?: {
    sdp?: string;
    type?: string;
    candidates?: ICECandidate[];
    candidate?: string;
    sdpMid?: string | null;
    sdpMLineIndex?: number | null;
    error?: string;
  };
}

/**
 * 视频流状态
 */
export type VideoStreamStatus = "connecting" | "connected" | "disconnected" | "error";

/**
 * 视频流状态数据
 */
export interface VideoStreamState {
  status: VideoStreamStatus;
  clientId: string | null;
  resolution: string | null;
  framerate: number | null;
  bitrate: number | null;
  error: string | null;
}

/**
 * 视频流统计
 */
export interface VideoStreamStats {
  framesReceived: number;
  framesDropped: number;
  bytesReceived: number;
  bitrate: number;
  framerate: number;
  lastFrameTime: number | null;
}

/**
 * 视频流选项
 */
export interface VideoStreamOptions {
  wsUrl: string;
  autoReconnect: boolean;
  maxReconnectAttempts: number;
  reconnectDelay: number;
}
