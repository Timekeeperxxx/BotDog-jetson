import { useCallback, useEffect, useRef, useState } from 'react';
import { Volume2, VolumeX } from 'lucide-react';
import voiceUrl from '../../assets/helmet-warning.wav';
import type { TrackOverlayData } from '../TrackOverlay1';

const MAX_OBSERVATION_AGE_MS = 1500;

interface VoicePlayer {
  context: AudioContext;
  buffer?: AudioBuffer;
  source?: AudioBufferSourceNode;
  expireTimer?: number;
  lastHeadAt?: number;
}

function stopPlayback(player: VoicePlayer) {
  window.clearTimeout(player.expireTimer);
  player.expireTimer = undefined;
  if (player.source) {
    player.source.stop();
    player.source.disconnect();
    player.source = undefined;
  }
}

export function HelmetVoiceButton({ overlay, videoConnected }: {
  overlay: TrackOverlayData | null;
  videoConnected: boolean;
}) {
  const playerRef = useRef<VoicePlayer | null>(null);
  const [state, setState] = useState<'off' | 'loading' | 'on' | 'error'>('off');

  const stop = useCallback(() => {
    const player = playerRef.current;
    playerRef.current = null;
    if (player) {
      stopPlayback(player);
      void player.context.close();
    }
  }, []);

  useEffect(() => stop, [stop]);

  async function toggle() {
    if (state === 'on') {
      stop();
      setState('off');
      return;
    }

    setState('loading');
    let player: VoicePlayer | null = null;
    try {
      const context = new AudioContext();
      player = { context };
      playerRef.current = player;
      // Resume directly from the click so later detection events can play sound.
      await context.resume();
      const response = await fetch(voiceUrl);
      if (!response.ok) throw new Error(`提示音加载失败 (${response.status})`);
      player.buffer = await context.decodeAudioData(await response.arrayBuffer());
      if (playerRef.current === player) setState('on');
    } catch (error) {
      if (player && playerRef.current !== player) return;
      stop();
      setState('error');
      console.error('未戴安全帽语音提醒启动失败', error);
    }
  }

  const observedAt = overlay?.person_received_at_ms;
  const hasHead = overlay?.detections?.some(({ class_name }) => class_name === 'head') ?? false;

  useEffect(() => {
    const player = playerRef.current;
    if (state !== 'on' || !player?.buffer) return;
    if (!videoConnected) {
      stopPlayback(player);
      return;
    }
    if (!hasHead || observedAt === undefined
        || (player.lastHeadAt !== undefined && observedAt <= player.lastHeadAt)) return;
    const remaining = MAX_OBSERVATION_AGE_MS - (performance.now() - observedAt);
    if (remaining <= 0) return;

    player.lastHeadAt = observedAt;
    window.clearTimeout(player.expireTimer);
    player.expireTimer = window.setTimeout(() => stopPlayback(player), remaining);
    if (player.source) return;

    const source = player.context.createBufferSource();
    source.buffer = player.buffer;
    source.loop = true;
    source.connect(player.context.destination);
    player.source = source;
    source.start();
  }, [state, videoConnected, hasHead, observedAt]);

  return (
    <button
      type="button"
      onClick={() => void toggle()}
      aria-label="未戴安全帽语音提醒"
      aria-pressed={state === 'on'}
      aria-busy={state === 'loading'}
      disabled={state === 'loading'}
      title={state === 'error' ? '语音提醒加载失败，点击重试' : '未戴安全帽语音提醒'}
      className={`flex items-center gap-1.5 whitespace-nowrap rounded-lg p-2 transition-all ${
        state === 'on' ? 'bg-emerald-300/15 text-emerald-200 hover:bg-emerald-300/25'
          : state === 'error' ? 'text-red-400 hover:bg-red-500/20'
          : 'hover:bg-white hover:text-black disabled:opacity-50'
      }`}
    >
      {state === 'on' ? <Volume2 size={22} aria-hidden="true" /> : <VolumeX size={22} aria-hidden="true" />}
      <span className="text-[10px] font-black">{state === 'error' ? '重试语音' : '安全帽语音'}</span>
    </button>
  );
}
