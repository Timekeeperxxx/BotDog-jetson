import { useCallback, useEffect, useRef, useState } from 'react';

export type WhepStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface WhepState {
  status: WhepStatus;
  error: string | null;
}

export interface WhepLatencyStats {
  totalMs: number;
  networkMs: number;
  jitterBufferMs: number;
  decodeMs: number;
}

// 未设置 VITE_WHEP_URL 时，自动使用当前页面的 hostname 拼接 MediaMTX 地址，
// 兼容后端托管 SPA 的场景（ARM64 部署无需写死 IP）。
const DEFAULT_WHEP_URL = `http://${window.location.hostname}:8889/cam/whep`;

// 重试退避阶梯（ms）
const RETRY_DELAYS_MS = [1000, 2000, 5000, 10000];
const STALLED_FRAME_SAMPLE_LIMIT = 8;
const MIN_STALL_RECONNECT_INTERVAL_MS = 30000;

// TypeScript DOM lib 中无 RTCRemoteInboundRtpStreamStats，按需声明
interface RemoteInboundRtpStats {
  kind?: string;
  roundTripTime?: number;
}

/**
 * 通过指定 IPv4 地址打开控制台时，仅保留 MediaMTX 在该地址上的 ICE 候选。
 * Jetson 同时连接相机网、Wi-Fi 和控制网；全部候选参与协商时，浏览器可能把
 * 视频媒体绕到高延迟 Wi-Fi，即使 WHEP 信令本身走的是控制网。
 */
export function filterWhepAnswerCandidates(answerSdp: string, whepUrl: string): string {
  let host: string;
  try {
    host = new URL(whepUrl).hostname;
  } catch {
    return answerSdp;
  }

  if (!/^(?:\d{1,3}\.){3}\d{1,3}$/.test(host)) return answerSdp;

  const newline = answerSdp.includes('\r\n') ? '\r\n' : '\n';
  const lines = answerSdp.split(/\r?\n/);
  const candidateLines = lines.filter((line) => line.startsWith('a=candidate:'));
  const matchingCandidates = candidateLines.filter((line) => line.trim().split(/\s+/)[4] === host);

  // MediaMTX 没公布该地址时保留原答案，避免因代理域名或 NAT 地址导致无法连接。
  if (candidateLines.length === 0 || matchingCandidates.length === 0) return answerSdp;

  return lines
    .filter((line) => !line.startsWith('a=candidate:') || line.trim().split(/\s+/)[4] === host)
    .join(newline);
}

export function useWhepVideo(customWhepUrl?: string, options?: { skipStats?: boolean }) {
  const skipStats = options?.skipStats;
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
  const prevInboundRef = useRef<{
    jitterBufferDelay: number;
    jitterBufferEmittedCount: number;
    totalDecodeTime: number;
    framesDecoded: number;
  } | null>(null);
  const [videoLatencyMs, setVideoLatencyMs] = useState<number | null>(null);
  const [videoLatencyStats, setVideoLatencyStats] = useState<WhepLatencyStats | null>(null);
  const [videoResolution, setVideoResolution] = useState<{ width: number | null; height: number | null }>({
    width: null,
    height: null,
  });
  const connectSessionIdRef = useRef(0);
  const shouldRetryRef = useRef(false);
  const retryAttemptsRef = useRef(0);
  const stalledFrameSamplesRef = useRef(0);
  const lastStallReconnectAtRef = useRef(0);
  // statusRef 与 React state 保持同步，用于同步判断当前连接状态
  const statusRef = useRef<WhepStatus>('disconnected');
  // 最新 connect 函数引用，供 retry timer 调用，避免 stale closure
  const connectFnRef = useRef<(() => Promise<void>) | null>(null);

  // 同步更新 statusRef 并触发 React 状态更新
  const setWhepStatus = useCallback((status: WhepStatus, error: string | null = null) => {
    statusRef.current = status;
    setState({ status, error });
  }, []);

  const cleanup = useCallback(async () => {
    connectingRef.current = false;
    connectSessionIdRef.current += 1;
    shouldRetryRef.current = false;
    statusRef.current = 'disconnected';

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
    stalledFrameSamplesRef.current = 0;
    setVideoLatencyMs(null);
    setVideoLatencyStats(null);
    setVideoResolution({ width: null, height: null });

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  const connect = useCallback(async () => {
    // 同步守卫：防止并发 connect() 调用，以及在已连接/连接中时重复触发
    if (connectingRef.current || statusRef.current === 'connecting' || statusRef.current === 'connected') {
      return;
    }
    connectingRef.current = true;  // 在第一个 await 之前同步占位，防止竞态

    // cleanup() 会：递增 sessionId、关闭 PC、清理定时器、DELETE WHEP session、
    // 清空 srcObject，并将 connectingRef 重置为 false
    await cleanup();

    // cleanup 已将 connectingRef 重置，重新占位继续建连
    connectingRef.current = true;
    shouldRetryRef.current = true;
    // sessionId 由 cleanup() 递增，旧回调凭此判断自身已失效
    const sessionId = connectSessionIdRef.current;

    const whepUrl = customWhepUrl || (import.meta.env.VITE_WHEP_URL as string | undefined) || DEFAULT_WHEP_URL;
    setWhepStatus('connecting');

    // 退避重试调度器——捕获当前 sessionId，仅对本次建连有效
    const scheduleRetry = (errorMsg: string) => {
      const delayIdx = Math.min(retryAttemptsRef.current, RETRY_DELAYS_MS.length - 1);
      const delay = RETRY_DELAYS_MS[delayIdx];
      retryAttemptsRef.current += 1;
      connectingRef.current = false;
      setWhepStatus('error', errorMsg);
      retryTimerRef.current = window.setTimeout(() => {
        retryTimerRef.current = null;
        // sessionId 不匹配（已被 cleanup/disconnect 作废）或已停止重试则放弃
        if (connectSessionIdRef.current !== sessionId || !shouldRetryRef.current) return;
        void connectFnRef.current?.();
      }, delay);
    };

    try {
      const pc = new RTCPeerConnection({
        iceServers: [],
        iceCandidatePoolSize: 0,
        bundlePolicy: 'max-bundle',
        rtcpMuxPolicy: 'require',
      });
      pcRef.current = pc;

      pc.addTransceiver('video', { direction: 'recvonly' });

      pc.ontrack = (event) => {
        if (connectSessionIdRef.current !== sessionId) return;
        const receiver = event.receiver as RTCRtpReceiver & { playoutDelayHint?: number };
        if ('playoutDelayHint' in receiver) {
          receiver.playoutDelayHint = 0;
        }
        if (videoRef.current) {
          videoRef.current.srcObject = event.streams[0];
        }
      };

      pc.onconnectionstatechange = () => {
        if (connectSessionIdRef.current !== sessionId) return;
        if (pc.connectionState === 'connected') {
          retryAttemptsRef.current = 0;
          connectingRef.current = false;
          setWhepStatus('connected');
          if (!statsTimerRef.current && !skipStats) {
            statsTimerRef.current = window.setInterval(async () => {
              // 旧 session 的定时器自我清除
              if (connectSessionIdRef.current !== sessionId) {
                window.clearInterval(statsTimerRef.current!);
                statsTimerRef.current = null;
                return;
              }
              const currentPc = pcRef.current;
              if (!currentPc) return;
              try {
                currentPc.getReceivers().forEach((receiver) => {
                  const lowLatencyReceiver = receiver as RTCRtpReceiver & { playoutDelayHint?: number };
                  if ('playoutDelayHint' in lowLatencyReceiver) {
                    lowLatencyReceiver.playoutDelayHint = 0;
                  }
                });

                const stats = await currentPc.getStats();
                let rttSeconds: number | null = null;
                let curInbound: {
                  jitterBufferDelay: number;
                  jitterBufferEmittedCount: number;
                  totalDecodeTime: number;
                  framesDecoded: number;
                } | null = null;

                stats.forEach((report) => {
                  // --- 网络单程延迟：从 ICE candidate-pair 获取 RTT ---
                  if (report.type === 'candidate-pair') {
                    const pair = report as RTCIceCandidatePairStats;
                    if (pair.state === 'succeeded' && pair.nominated) {
                      const rtt = pair.currentRoundTripTime;
                      if (typeof rtt === 'number' && rtt > 0 && rttSeconds === null) {
                        rttSeconds = rtt;
                      }
                    }
                  }
                  // --- 抖动缓冲区 + 解码延迟：从 inbound-rtp 获取累计值 ---
                  if (report.type === 'inbound-rtp') {
                    const r = report as RTCInboundRtpStreamStats;
                    if (r.kind === 'video') {
                      curInbound = {
                        jitterBufferDelay: typeof r.jitterBufferDelay === 'number' ? r.jitterBufferDelay : 0,
                        jitterBufferEmittedCount: typeof r.jitterBufferEmittedCount === 'number' ? r.jitterBufferEmittedCount : 0,
                        totalDecodeTime: typeof r.totalDecodeTime === 'number' ? r.totalDecodeTime : 0,
                        framesDecoded: typeof r.framesDecoded === 'number' ? r.framesDecoded : 0,
                      };
                    }
                  }
                });

                // 备用：从 remote-inbound-rtp 获取 RTT
                if (rttSeconds === null) {
                  stats.forEach((report) => {
                    if (rttSeconds !== null) return;
                    if (report.type === 'remote-inbound-rtp') {
                      const r = report as RemoteInboundRtpStats;
                      if (r.kind === 'video') {
                        const rtt = r.roundTripTime;
                        if (typeof rtt === 'number' && rtt > 0) rttSeconds = rtt;
                      }
                    }
                  });
                }

                // 用增量计算本周期的平均 jitter buffer 延迟和解码时间
                let jitterBufferMs = 0;
                let decodeMs = 0;
                let decodedFramesDelta: number | null = null;
                if (curInbound && prevInboundRef.current) {
                  const prev = prevInboundRef.current;
                  const cur = curInbound as {
                    jitterBufferDelay: number;
                    jitterBufferEmittedCount: number;
                    totalDecodeTime: number;
                    framesDecoded: number;
                  };
                  const deltaEmitted = cur.jitterBufferEmittedCount - prev.jitterBufferEmittedCount;
                  const deltaJitter = cur.jitterBufferDelay - prev.jitterBufferDelay;
                  const deltaFrames = cur.framesDecoded - prev.framesDecoded;
                  const deltaDecode = cur.totalDecodeTime - prev.totalDecodeTime;
                  decodedFramesDelta = deltaFrames;
                  if (deltaEmitted > 0) jitterBufferMs = (deltaJitter / deltaEmitted) * 1000;
                  if (deltaFrames > 0) decodeMs = (deltaDecode / deltaFrames) * 1000;
                }
                if (curInbound) {
                  prevInboundRef.current = curInbound as {
                    jitterBufferDelay: number;
                    jitterBufferEmittedCount: number;
                    totalDecodeTime: number;
                    framesDecoded: number;
                  };
                }

                // 总延迟 = 网络单程 + 抖动缓冲区 + 解码
                if (rttSeconds !== null || jitterBufferMs > 0) {
                  const networkMs = rttSeconds !== null ? (rttSeconds * 1000) / 2 : 0;
                  const totalMs = Math.round(networkMs + jitterBufferMs + decodeMs);
                  setVideoLatencyMs(totalMs);
                  setVideoLatencyStats({
                    totalMs,
                    networkMs: Math.round(networkMs),
                    jitterBufferMs: Math.round(jitterBufferMs),
                    decodeMs: Math.round(decodeMs),
                  });
                }

                // 高 jitter 并不等于视频已经停止；按缓冲区阈值主动重连会不断丢弃
                // 当前会话和关键帧。仅在页面可见且连续多次没有解码新帧时重连。
                if (!skipStats && decodedFramesDelta !== null) {
                  if (decodedFramesDelta > 0) {
                    stalledFrameSamplesRef.current = 0;
                  } else {
                    stalledFrameSamplesRef.current += 1;
                  }

                  const now = Date.now();
                  const shouldReconnect =
                    document.visibilityState === 'visible'
                    && stalledFrameSamplesRef.current >= STALLED_FRAME_SAMPLE_LIMIT
                    && now - lastStallReconnectAtRef.current >= MIN_STALL_RECONNECT_INTERVAL_MS;
                  if (shouldReconnect) {
                    lastStallReconnectAtRef.current = now;
                    stalledFrameSamplesRef.current = 0;
                    void (async () => {
                      await cleanup();
                      window.setTimeout(() => {
                        void connectFnRef.current?.();
                      }, 250);
                    })();
                  }
                }
              } catch {
                // ignore stats errors
              }
            }, 1000);
          }
        } else if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
          if (statsTimerRef.current) {
            window.clearInterval(statsTimerRef.current);
            statsTimerRef.current = null;
          }
          setVideoLatencyMs(null);
          setVideoLatencyStats(null);
          if (shouldRetryRef.current) {
            scheduleRetry('WHEP 连接失败');
          } else {
            connectingRef.current = false;
            setWhepStatus('error', 'WHEP 连接失败');
          }
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const response = await fetch(whepUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/sdp' },
        body: offer.sdp,
      });

      if (connectSessionIdRef.current !== sessionId) return;

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

      const answerSdp = filterWhepAnswerCandidates(await response.text(), whepUrl);
      if (connectSessionIdRef.current !== sessionId || pc.signalingState === 'closed') {
        return;
      }
      await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });
      // 信令完成；ICE 连接状态由 onconnectionstatechange 接管

    } catch (error) {
      if (connectSessionIdRef.current !== sessionId) return;
      if (shouldRetryRef.current) {
        scheduleRetry(String(error));
      } else {
        connectingRef.current = false;
        setWhepStatus('error', String(error));
      }
    }
  }, [cleanup, customWhepUrl, setWhepStatus, skipStats]);

  // 每次渲染同步更新 connectFnRef，让 retry timer 始终调用最新的 connect
  connectFnRef.current = connect;

  const disconnect = useCallback(async () => {
    await cleanup();
    retryAttemptsRef.current = 0;
    setWhepStatus('disconnected');
  }, [cleanup, setWhepStatus]);

  // customWhepUrl 变化时：cleanup 旧连接并用新 URL 重新 connect
  const isFirstMountRef = useRef(true);
  useEffect(() => {
    if (isFirstMountRef.current) {
      isFirstMountRef.current = false;
      return;
    }
    retryAttemptsRef.current = 0;
    void (async () => {
      await cleanup();
      // cleanup 已将 statusRef 置为 'disconnected'，connect() 守卫不会拦截
      void connectFnRef.current?.();
    })();
  }, [customWhepUrl, cleanup]);

  // 当 video 元素变化时（如 Tab 切换导致重新挂载），重新绑定 srcObject
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

  // Tab 切换导致 video 重新挂载时，重新绑定 srcObject
  useEffect(() => {
    const timer = setInterval(() => {
      const video = videoRef.current;
      const pc = pcRef.current;
      if (!video || !pc) return;
      if (video.srcObject) return;

      const receivers = pc.getReceivers();
      if (receivers.length === 0) return;

      const stream = new MediaStream(
        receivers.map((r) => r.track).filter(Boolean)
      );
      video.srcObject = stream;
    }, 500);

    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    return () => {
      void cleanup();
    };
  }, [cleanup]);

  return {
    status: state,
    videoRef,
    videoLatencyMs,
    videoLatencyStats,
    videoResolution,
    connect,
    disconnect,
  };
}
