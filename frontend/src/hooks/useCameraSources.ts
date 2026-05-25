import { useEffect, useState } from 'react';
import { getApiUrl } from '../config/api';
import type { VideoSource } from '../types/admin';

export interface OmniCameraUrls {
  back?: string;
  left?: string;
  right?: string;
}

export interface UseCameraSourcesState {
  cam2WhepUrl: string | undefined;
  frontWhepUrl: string | undefined;
  omniUrls: OmniCameraUrls;
}

const SECONDARY_NAMES = ['cam2', 'cam3', 'cam4'] as const;
const SECONDARY_TO_OMNI: Record<(typeof SECONDARY_NAMES)[number], keyof OmniCameraUrls> = {
  cam2: 'back',
  cam3: 'left',
  cam4: 'right',
};

function rewriteHost(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  return url.replace('127.0.0.1', window.location.hostname);
}

export function useCameraSources(): UseCameraSourcesState {
  const [cam2WhepUrl, setCam2WhepUrl] = useState<string | undefined>(undefined);
  const [frontWhepUrl, setFrontWhepUrl] = useState<string | undefined>(undefined);
  const [omniUrls, setOmniUrls] = useState<OmniCameraUrls>({});

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const res = await fetch(getApiUrl('/api/v1/video-sources/active'));
        if (!res.ok) return;
        const data = await res.json();
        const sources: VideoSource[] = data.sources || [];
        if (cancelled) return;

        const byName = new Map<string, VideoSource>();
        for (const s of sources) byName.set(s.name, s);

        const next: OmniCameraUrls = {};
        for (const name of SECONDARY_NAMES) {
          const url = rewriteHost(byName.get(name)?.whep_url);
          if (url) next[SECONDARY_TO_OMNI[name]] = url;
        }

        const cam2Url = rewriteHost(byName.get('cam2')?.whep_url)
          ?? rewriteHost(sources.find((s) => !s.is_primary)?.whep_url);

        const cam1Url = rewriteHost(byName.get('cam1')?.whep_url)
          ?? rewriteHost(sources.find((s) => s.is_primary)?.whep_url);

        if (cam2Url) setCam2WhepUrl(cam2Url);
        if (cam1Url) setFrontWhepUrl(cam1Url);
        setOmniUrls(next);
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
    frontWhepUrl,
    omniUrls,
  };
}
