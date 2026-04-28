import { useCallback, useEffect, useState } from 'react';
import { getApiUrl } from '../config/api';

export interface UseAudioControlState {
  isAudioPlaying: boolean;
  toggleAudio: () => Promise<void>;
}

export function useAudioControl(): UseAudioControlState {
  const [isAudioPlaying, setIsAudioPlaying] = useState(false);

  useEffect(() => {
    const fetchAudioStatus = async () => {
      try {
        const res = await fetch(getApiUrl('/api/v1/audio/status'));
        if (res.ok) {
          const data = await res.json();
          setIsAudioPlaying(data.playing);
        }
      } catch {}
    };
    fetchAudioStatus();
    const timer = setInterval(fetchAudioStatus, 2000);
    return () => clearInterval(timer);
  }, []);

  const toggleAudio = useCallback(async () => {
    try {
      const endpoint = isAudioPlaying ? '/api/v1/audio/stop' : '/api/v1/audio/play';
      const res = await fetch(getApiUrl(endpoint), { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setIsAudioPlaying(data.playing);
      }
    } catch (err) {
      console.error('切换音频失败:', err);
    }
  }, [isAudioPlaying]);

  return {
    isAudioPlaying,
    toggleAudio,
  };
}
