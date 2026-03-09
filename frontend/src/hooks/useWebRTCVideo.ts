/**
 * WebRTC视频流Hook - 修复版本
 * 修复：添加资源清理和重连保护
 */

import { useEffect, useRef, useState } from 'react';
import { getWsUrl } from '../config/api';

export interface WebRTCStatus {
  status: 'disconnected' | 'connecting' | 'connected' | 'error';
  error: string | null;
}

export function useWebRTCVideo() {
  const [status, setStatus] = useState<WebRTCStatus>({
    status: 'disconnected',
    error: null,
  });

  const videoRef = useRef<HTMLVideoElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const connectAttemptRef = useRef(0);
  const isConnectingRef = useRef(false);  // 防止重复连接

  // 连接WebRTC
  const connect = async () => {
    console.log("🚀 尝试初始化 WebRTC...");

    // 防止重复连接
    if (wsRef.current?.readyState === WebSocket.OPEN || status.status === 'connected') {
      console.log('✅ WebRTC已连接，跳过重复连接');
      return;
    }

    // 防止同时进行多个连接尝试
    if (isConnectingRef.current) {
      console.log('⏳ WebRTC正在连接中，跳过重复尝试');
      return;
    }

    // 关闭旧连接
    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
      console.log('🔄 关闭旧WebRTC连接');
      wsRef.current.close();
      wsRef.current = null;
    }
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }

    isConnectingRef.current = true;

    try {
      setStatus({ status: 'connecting', error: null });
      console.log('🔗 正在连接WebRTC信令服务器...');

      // 1. 连接到信令服务器
      const ws = new WebSocket(getWsUrl('/ws/webrtc'));
      wsRef.current = ws;

      ws.onopen = async () => {
        console.log('✅ WebRTC信令连接已建立');

        try {
          // 2. Create RTCPeerConnection
          const pc = new RTCPeerConnection({
            iceServers: [
              { urls: 'stun:stun.l.google.com:19302' },
            ],
          });
          pcRef.current = pc;

          // 3. Handle ICE candidates
          pc.onicecandidate = (event) => {
            if (event.candidate && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({
                msg_type: 'ice_candidate',
                payload: {
                  candidate: event.candidate.candidate,
                  sdpMid: event.candidate.sdpMid,
                  sdpMLineIndex: event.candidate.sdpMLineIndex,
                },
              }));
            }
          };

          // 4. Handle connection state changes
          pc.onconnectionstatechange = () => {
            console.log('📡 WebRTC连接状态:', pc.connectionState);
            if (pc.connectionState === 'connected') {
              setStatus({ status: 'connected', error: null });
            } else if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
              setStatus({ status: 'error', error: 'WebRTC连接失败' });
            }
          };

          // 5. Receive remote video stream
          pc.ontrack = (event) => {
            console.log('🎥 接收到远程视频流:', event.streams[0]);
            console.log('📹 Stream ID:', event.streams[0].id);
            console.log('📹 Stream active:', event.streams[0].active);
            console.log('📹 Track count:', event.streams[0].getTracks().length);

            if (videoRef.current) {
              console.log('✅ videoRef.current 存在');
              console.log('📺 之前 srcObject:', videoRef.current.srcObject);

              videoRef.current.srcObject = event.streams[0];

              console.log('📺 新的 srcObject:', videoRef.current.srcObject);
              console.log('📺 Video readyState:', videoRef.current.readyState);

              videoRef.current.play().then(() => {
                console.log('✅ 视频播放成功');
              }).catch(err => {
                console.error('❌ 视频播放错误:', err);
              });

              // 验证流是否挂载
              setTimeout(() => {
                if (videoRef.current) {
                  console.log('📺 2秒后检查:');
                  console.log('  - srcObject:', videoRef.current.srcObject);
                  console.log('  - readyState:', videoRef.current.readyState);
                  console.log('  - videoWidth:', videoRef.current.videoWidth);
                  console.log('  - videoHeight:', videoRef.current.videoHeight);
                  console.log('  - paused:', videoRef.current.paused);
                }
              }, 2000);
            } else {
              console.error('❌ videoRef.current 不存在！');
            }
          };

          // 6. 创建并发送Offer
          pc.addTransceiver('video', { direction: 'recvonly' });
          pc.addTransceiver('audio', { direction: 'recvonly' });

          const offer = await pc.createOffer();
          await pc.setLocalDescription(offer);

          // 检查 WebSocket 连接状态
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            console.log('📤 向服务器发送offer');
            wsRef.current.send(JSON.stringify({
              msg_type: 'offer',
              payload: {
                sdp: offer.sdp,
                type: offer.type,
              },
            }));
          } else {
            console.error('❌ WebSocket已关闭，无法发送offer');
            setStatus({ status: 'error', error: 'WebSocket连接已关闭' });
          }
        } catch (error) {
          console.error('❌ 创建WebRTC连接失败:', error);
          setStatus({ status: 'error', error: String(error) });
          if (wsRef.current) {
            wsRef.current.close();
          }
        }
      };

      ws.onmessage = async (event) => {
        try {
          const message = JSON.parse(event.data);
          console.log('📥 收到WebRTC消息:', message.msg_type);

          if (message.msg_type === 'answer') {
            const pc = pcRef.current;
            if (pc) {
              await pc.setRemoteDescription(new RTCSessionDescription({
                type: 'answer',
                sdp: message.payload.sdp,
              }));
              console.log('✅ 已设置远程描述（answer）');
            }
          } else if (message.msg_type === 'ice_candidate') {
            const pc = pcRef.current;
            if (pc && message.payload.candidate) {
              await pc.addIceCandidate(new RTCIceCandidate({
                candidate: message.payload.candidate,
                sdpMid: message.payload.sdpMid,
                sdpMLineIndex: message.payload.sdpMLineIndex,
              }));
            }
          }
        } catch (error) {
          console.error('❌ 处理WebRTC消息失败:', error);
        }
      };

      ws.onerror = (error) => {
        console.error('❌ WebRTC信令错误:', error);
        setStatus({ status: 'error', error: '信令连接失败' });
        isConnectingRef.current = false;  // 释放连接锁
      };

      ws.onclose = (event) => {
        console.log(`🔌 WebRTC信令连接已关闭: code=${event.code}`);
        setStatus({ status: 'disconnected', error: null });
        isConnectingRef.current = false;  // 释放连接锁
      };
    } catch (error) {
      console.error('❌ 连接WebRTC失败:', error);
      setStatus({ status: 'error', error: String(error) });
      isConnectingRef.current = false;  // 释放连接锁
    }
  };

  // Disconnect
  const disconnect = () => {
    console.log('断开WebRTC连接...');
    isConnectingRef.current = false;  // 释放连接锁
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
    setStatus({ status: 'disconnected', error: null });
  };

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, []);

  return {
    status,
    videoRef,
    connect,
    disconnect,
  };
}
