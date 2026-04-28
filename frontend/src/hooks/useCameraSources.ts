import { useEffect, useState } from 'react';
import { getApiUrl } from '../config/api';
import type { VideoSource } from '../types/admin';

export interface UseCameraSourcesState {
  cam2WhepUrl: string | undefined;
}

export function useCameraSources(): UseCameraSourcesState {
  const [cam2WhepUrl, setCam2WhepUrl] = useState<string | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const res = await fetch(getApiUrl('/api/v1/video-sources/active'));
        if (!res.ok) return;
        const data = await res.json();
        const sources: VideoSource[] = data.sources || [];
        const secondary = sources.find((s) => !s.is_primary);
        if (secondary?.whep_url && !cancelled) {
          const fixedUrl = secondary.whep_url.replace('127.0.0.1', window.location.hostname);
          setCam2WhepUrl(fixedUrl);
        }
      } catch (err) {
        console.error('获取视频源配置失败:', err);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return {
    cam2WhepUrl,
  };
}
