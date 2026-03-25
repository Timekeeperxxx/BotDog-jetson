import { useCallback, useEffect, useRef, useState } from 'react';

export type WhepStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface WhepState {
  status: WhepStatus;
  error: string | null;
}

const DEFAULT_WHEP_URL = 'http://127.0.0.1:8889/cam/whep';

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

                stats.forEach((report) => {
                  if (rttSeconds !== null) return;
                  if (report.type === 'candidate-pair' && report.state === 'succeeded' && report.nominated) {
                    const currentRtt = (report as RTCIceCandidatePairStats).currentRoundTripTime;
                    if (typeof currentRtt === 'number' && currentRtt > 0) {
                      rttSeconds = currentRtt;
                    }
                  }
                });

                if (rttSeconds === null) {
                  stats.forEach((report) => {
                    if (rttSeconds !== null) return;
                    if (report.type === 'remote-inbound-rtp' && report.kind === 'video') {
                      const currentRtt = (report as any).roundTripTime;
                      if (typeof currentRtt === 'number' && currentRtt > 0) {
                        rttSeconds = currentRtt;
                      }
                    }
                  });
                }

                if (rttSeconds !== null) {
                  const latencyMs = Math.round((rttSeconds * 1000) / 2);
                  setVideoLatencyMs(latencyMs);
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
