/**
 * WebRTC 连接管理 Hook。
 *
 * 职责边界：
 * - 管理 WebRTC 对等连接
 * - 处理 SDP offer/answer 交换
 * - 处理 ICE 候选交换
 * - 自动重连机制
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  VideoStreamStatus,
  WebRTCSignalingMessage,
  VideoStreamOptions,
} from "../types/video";
import { getWsUrl } from "../config/api";

/**
 * Hook 返回值
 */
export interface UseWebRTCReturn {
  status: VideoStreamStatus;
  error: string | null;
  clientId: string | null;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  connect: () => void;
  disconnect: () => void;
}

/**
 * WebRTC Hook
 *
 * @param options 视频流选项
 * @returns 连接状态和控制方法
 */
export function useWebRTC(
  options: Partial<VideoStreamOptions> = {}
): UseWebRTCReturn {
  const {
    wsUrl,
    autoReconnect = true,
    maxReconnectAttempts = 10,
    reconnectDelay = 1000,
  } = options;

  // 使用环境变量或传入的 URL
  const signalingUrl = wsUrl || getWsUrl('/ws/webrtc');

  const [status, setStatus] = useState<VideoStreamStatus>("disconnected");
  const [error, setError] = useState<string | null>(null);
  const [clientId, setClientId] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const remoteStreamRef = useRef<MediaStream | null>(null);

  /**
   * 创建 WebRTC 对等连接
   */
  const createPeerConnection = useCallback(() => {
    const pc = new RTCPeerConnection({
      iceServers: [
        { urls: "stun:stun.l.google.com:19302" },
      ],
    });

    // ICE 候选回调
    pc.onicecandidate = (event) => {
      if (event.candidate && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          msg_type: "ice_candidate",
          payload: {
            candidate: event.candidate.candidate,
            sdpMid: event.candidate.sdpMid,
            sdpMLineIndex: event.candidate.sdpMLineIndex,
          },
        }));
      }
    };

    // ICE 连接状态变化回调
    pc.oniceconnectionstatechange = () => {
      console.log("ICE 连接状态:", pc.iceConnectionState);
    };

    // 对等连接状态变化回调
    pc.onconnectionstatechange = () => {
      console.log("对等连接状态:", pc.connectionState);
      if (pc.connectionState === "connected") {
        setStatus("connected");
        setError(null);
      } else if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
        setStatus("error");
        setError("WebRTC 连接失败");
      }
    };

    // 远程流回调
    pc.ontrack = (event) => {
      console.log("接收到远程流:", event.streams[0]);
      if (videoRef.current) {
        remoteStreamRef.current = event.streams[0];
        videoRef.current.srcObject = event.streams[0];
      }
    };

    return pc;
  }, []);

  /**
   * 清理连接
   */
  const cleanup = useCallback(() => {
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    if (remoteStreamRef.current) {
      remoteStreamRef.current = null;
    }

    if (reconnectTimeoutRef.current) {
      window.clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  /**
   * 连接服务器
   */
  const connect = useCallback(() => {
    try {
      setStatus("connecting");
      setError(null);

      const ws = new WebSocket(signalingUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("WebRTC 信令 WebSocket 连接已建立");
      };

      ws.onmessage = async (event) => {
        try {
          const message = JSON.parse(event.data) as WebRTCSignalingMessage;
          console.log("收到信令消息:", message.msg_type);

          switch (message.msg_type) {
            case "welcome":
              setClientId(message.client_id || null);
              console.log("客户端 ID:", message.client_id);

              // 创建对等连接并添加视频接收轨道
              const pc = createPeerConnection();
              pcRef.current = pc;
              pc.addTransceiver("video", { direction: "recvonly" });

              // 创建 SDP offer
              const offer = await pc.createOffer();
              await pc.setLocalDescription(offer);

              // 发送 offer
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({
                  msg_type: "offer",
                  payload: {
                    sdp: pc.localDescription?.sdp,
                    type: "offer",
                  },
                }));
              }
              break;

            case "answer":
              // 接收到 SDP answer
              if (pcRef.current && message.payload?.sdp) {
                await pcRef.current.setRemoteDescription(
                  new RTCSessionDescription({
                    sdp: message.payload.sdp,
                    type: "answer",
                  })
                );
                console.log("已设置远程描述（answer）");
              }
              break;

            case "ice_candidates":
              // 接收到 ICE 候选列表
              if (pcRef.current && message.payload?.candidates) {
                for (const candidate of message.payload.candidates) {
                  await pcRef.current.addIceCandidate(
                    new RTCIceCandidate(candidate)
                  );
                }
                console.log(`已添加 ${message.payload.candidates.length} 个 ICE 候选`);
              }
              break;

            case "ice_candidate":
              // 接收到单个 ICE 候选
              if (pcRef.current && message.payload?.candidate) {
                await pcRef.current.addIceCandidate(
                  new RTCIceCandidate({
                    candidate: message.payload.candidate,
                    sdpMid: message.payload.sdpMid,
                    sdpMLineIndex: message.payload.sdpMLineIndex,
                  })
                );
              }
              break;

            case "error":
              // 错误消息
              console.error("信令错误:", message.payload?.error);
              setError(message.payload?.error || "未知错误");
              break;

            default:
              console.warn("未知消息类型:", message.msg_type);
          }
        } catch (err) {
          console.error("处理信令消息失败:", err);
        }
      };

      ws.onclose = (event) => {
        console.log(`WebRTC 信令 WebSocket 连接关闭: code=${event.code}`);

        setStatus("disconnected");
        setClientId(null);

        // 自动重连
        if (autoReconnect && event.code !== 1000 && reconnectAttemptsRef.current < maxReconnectAttempts) {
          reconnectAttemptsRef.current += 1;
          const delay = Math.min(
            reconnectDelay * Math.pow(2, reconnectAttemptsRef.current - 1),
            30000
          );

          console.log(
            `WebRTC 将在 ${delay}ms 后重连（第 ${reconnectAttemptsRef.current} 次）`
          );

          reconnectTimeoutRef.current = window.setTimeout(() => {
            connect();
          }, delay);
        } else if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
          setError("WebRTC 重连次数已达上限");
          setStatus("error");
        }
      };

      ws.onerror = () => {
        setStatus("error");
        setError("WebRTC 信令 WebSocket 连接错误");
      };
    } catch (err) {
      setStatus("error");
      setError(`连接失败: ${err}`);
    }
  }, [signalingUrl, autoReconnect, maxReconnectAttempts, reconnectDelay, createPeerConnection]);

  /**
   * 断开连接
   */
  const disconnect = useCallback(() => {
    cleanup();
    setStatus("disconnected");
    setError(null);
    setClientId(null);
    reconnectAttemptsRef.current = 0;
  }, [cleanup]);

  /**
   * 组件卸载时清理
   */
  useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);

  return {
    status,
    error,
    clientId,
    videoRef,
    connect,
    disconnect,
  };
}
