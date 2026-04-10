import { useCallback, useEffect, useRef, useState } from 'react';

export type WhepStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface WhepState {
  status: WhepStatus;
  error: string | null;
}

// 未设置 VITE_WHEP_URL 时，自动使用当前页面的 hostname 拼接 MediaMTX 地址，
// 兼容后端托管 SPA 的场景（OrangePi 部署无需写死 IP）。
const DEFAULT_WHEP_URL = `http://${window.location.hostname}:8889/cam/whep`;

export function useWhepVideo(customWhepUrl?: string) {
  const [state, setState] = useState<WhepState>({
    status: 'disconnected',
    error: null,
  });

  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const sessionUrlRef = useRef<string | null>(null);
  const connectingRef = useRef(false);
  const retryTimerRef = useRef<number | null>(null);
  const statsTimerRef = useRef<number | null>(null);
  // 上一次 inbound-rtp 快照，用于增量计算 jitter buffer 和 decode 延迟
  const prevInboundRef = useRef<{ jitterBufferDelay: number; jitterBufferEmittedCount: number; totalDecodeTime: number; framesDecoded: number } | null>(null);
  const [videoLatencyMs, setVideoLatencyMs] = useState<number | null>(null);
  const [videoResolution, setVideoResolution] = useState<{ width: number | null; height: number | null }>({
    width: null,
    height: null,
  });
  const connectSessionIdRef = useRef(0);
  const shouldRetryRef = useRef(true);

  const cleanup = useCallback(async () => {
    connectingRef.current = false;
    connectSessionIdRef.current += 1;
    shouldRetryRef.current = false;

    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }

    if (statsTimerRef.current) {
      window.clearInterval(statsTimerRef.current);
      statsTimerRef.current = null;
    }

    if (retryTimerRef.current) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }

    if (sessionUrlRef.current) {
      try {
        await fetch(sessionUrlRef.current, { method: 'DELETE' });
      } catch {
        // ignore cleanup errors
      }
      sessionUrlRef.current = null;
    }

    prevInboundRef.current = null;
    setVideoLatencyMs(null);
    setVideoResolution({ width: null, height: null });

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  const connect = useCallback(async () => {
    if (connectingRef.current) {
      return;
    }

    await cleanup();
    shouldRetryRef.current = true;

    const sessionId = connectSessionIdRef.current + 1;
    connectSessionIdRef.current = sessionId;

    const whepUrl = customWhepUrl || (import.meta.env.VITE_WHEP_URL as string | undefined) || DEFAULT_WHEP_URL;

    connectingRef.current = true;
    setState({ status: 'connecting', error: null });

    try {
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
      });
      pcRef.current = pc;

      pc.addTransceiver('video', { direction: 'recvonly' });

      pc.ontrack = (event) => {
        if (videoRef.current) {
          videoRef.current.srcObject = event.streams[0];
        }
      };

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'connected') {
          setState({ status: 'connected', error: null });
          if (!statsTimerRef.current) {
            statsTimerRef.current = window.setInterval(async () => {
              const currentPc = pcRef.current;
              if (!currentPc) return;
              try {
                const stats = await currentPc.getStats();
                let rttSeconds: number | null = null;
                let curInbound: { jitterBufferDelay: number; jitterBufferEmittedCount: number; totalDecodeTime: number; framesDecoded: number } | null = null;

                stats.forEach((report) => {
                  // --- 网络单程延迟：从 ICE candidate-pair 获取 RTT ---
                  if (report.type === 'candidate-pair' && (report as any).state === 'succeeded' && (report as any).nominated) {
                    const rtt = (report as RTCIceCandidatePairStats).currentRoundTripTime;
                    if (typeof rtt === 'number' && rtt > 0 && rttSeconds === null) {
                      rttSeconds = rtt;
                    }
                  }
                  // --- 抖动缓冲区 + 解码延迟：从 inbound-rtp 获取累计值 ---
                  if (report.type === 'inbound-rtp' && (report as any).kind === 'video') {
                    const r = report as any;
                    curInbound = {
                      jitterBufferDelay: typeof r.jitterBufferDelay === 'number' ? r.jitterBufferDelay : 0,
                      jitterBufferEmittedCount: typeof r.jitterBufferEmittedCount === 'number' ? r.jitterBufferEmittedCount : 0,
                      totalDecodeTime: typeof r.totalDecodeTime === 'number' ? r.totalDecodeTime : 0,
                      framesDecoded: typeof r.framesDecoded === 'number' ? r.framesDecoded : 0,
                    };
                  }
                });

                // 备用：从 remote-inbound-rtp 获取 RTT
                if (rttSeconds === null) {
                  stats.forEach((report) => {
                    if (rttSeconds !== null) return;
                    if (report.type === 'remote-inbound-rtp' && (report as any).kind === 'video') {
                      const rtt = (report as any).roundTripTime;
                      if (typeof rtt === 'number' && rtt > 0) rttSeconds = rtt;
                    }
                  });
                }

                // 用增量计算本周期的平均 jitter buffer 延迟和解码时间
                let jitterBufferMs = 0;
                let decodeMs = 0;
                if (curInbound && prevInboundRef.current) {
                  const prev = prevInboundRef.current;
                  const cur = curInbound as { jitterBufferDelay: number; jitterBufferEmittedCount: number; totalDecodeTime: number; framesDecoded: number };
                  const deltaEmitted = cur.jitterBufferEmittedCount - prev.jitterBufferEmittedCount;
                  const deltaJitter = cur.jitterBufferDelay - prev.jitterBufferDelay;
                  const deltaFrames = cur.framesDecoded - prev.framesDecoded;
                  const deltaDecode = cur.totalDecodeTime - prev.totalDecodeTime;
                  if (deltaEmitted > 0) jitterBufferMs = (deltaJitter / deltaEmitted) * 1000;
                  if (deltaFrames > 0) decodeMs = (deltaDecode / deltaFrames) * 1000;
                }
                if (curInbound) prevInboundRef.current = curInbound as { jitterBufferDelay: number; jitterBufferEmittedCount: number; totalDecodeTime: number; framesDecoded: number };

                // 总延迟 = 网络单程 + 抖动缓冲区 + 解码
                if (rttSeconds !== null || jitterBufferMs > 0) {
                  const networkMs = rttSeconds !== null ? (rttSeconds * 1000) / 2 : 0;
                  const totalMs = Math.round(networkMs + jitterBufferMs + decodeMs);
                  setVideoLatencyMs(totalMs);
                }
              } catch {
                // ignore stats errors
              }
            }, 1000);
          }
        } else if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
          setState({ status: 'error', error: 'WHEP 连接失败' });
          if (statsTimerRef.current) {
            window.clearInterval(statsTimerRef.current);
            statsTimerRef.current = null;
          }
          setVideoLatencyMs(null);
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const response = await fetch(whepUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/sdp' },
        body: offer.sdp,
      });

      if (!response.ok) {
        throw new Error(`WHEP 响应失败: ${response.status}`);
      }

      const sessionUrl = response.headers.get('Location');
      if (sessionUrl) {
        try {
          sessionUrlRef.current = new URL(sessionUrl, whepUrl).toString();
        } catch {
          sessionUrlRef.current = sessionUrl;
        }
      }

      const answerSdp = await response.text();
      if (connectSessionIdRef.current !== sessionId || pc.signalingState === 'closed') {
        return;
      }
      await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });

      if (retryTimerRef.current) {
        window.clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }

      connectingRef.current = false;
    } catch (error) {
      if (connectSessionIdRef.current !== sessionId) {
        return;
      }
      await cleanup();
      connectingRef.current = false;
      setState({ status: 'error', error: String(error) });
    }
  }, [cleanup, state.status]);

  const disconnect = useCallback(async () => {
    await cleanup();
    setState({ status: 'disconnected', error: null });
  }, [cleanup]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) {
      return;
    }

    const updateResolution = () => {
      const width = video.videoWidth || null;
      const height = video.videoHeight || null;
      if (width && height) {
        setVideoResolution({ width, height });
      }
    };

    updateResolution();
    video.addEventListener('loadedmetadata', updateResolution);
    video.addEventListener('resize', updateResolution);

    return () => {
      video.removeEventListener('loadedmetadata', updateResolution);
      video.removeEventListener('resize', updateResolution);
    };
  }, [videoRef]);

  useEffect(() => {
    return () => {
      void cleanup();
    };
  }, [cleanup]);

  return {
    status: state,
    videoRef,
    videoLatencyMs,
    videoResolution,
    connect,
    disconnect,
  };
}
