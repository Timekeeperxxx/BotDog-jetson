import { useCallback, useEffect, useRef, useState } from 'react';

type FullscreenDocument = Document & {
  webkitFullscreenElement?: Element | null;
  webkitExitFullscreen?: () => Promise<void> | void;
};

type FullscreenElement = HTMLElement & {
  webkitRequestFullscreen?: () => Promise<void> | void;
};

export interface UseFullscreenControlState {
  isUiFullscreen: boolean;
  toggleFullscreen: () => void;
}

export function useFullscreenControl(): UseFullscreenControlState {
  const [isUiFullscreen, setIsUiFullscreen] = useState(false);
  const fullscreenRequestedRef = useRef(false);

  const toggleFullscreen = useCallback(() => {
    const doc = document as FullscreenDocument;
    if (!isUiFullscreen) {
      const elem = document.documentElement as FullscreenElement;
      fullscreenRequestedRef.current = true;
      if (elem.requestFullscreen) elem.requestFullscreen().catch(console.error);
      else if (elem.webkitRequestFullscreen) elem.webkitRequestFullscreen();
    } else {
      fullscreenRequestedRef.current = false;
      if (doc.exitFullscreen) doc.exitFullscreen();
      else if (doc.webkitExitFullscreen) doc.webkitExitFullscreen();
    }
  }, [isUiFullscreen]);

  useEffect(() => {
    const doc = document as FullscreenDocument;
    const handler = () => {
      const isFullscreen = !!(document.fullscreenElement || doc.webkitFullscreenElement);
      setIsUiFullscreen(isFullscreen);
      if (!isFullscreen && fullscreenRequestedRef.current) {
        fullscreenRequestedRef.current = false;
      }
    };
    document.addEventListener('fullscreenchange', handler);
    document.addEventListener('webkitfullscreenchange', handler);
    return () => {
      document.removeEventListener('fullscreenchange', handler);
      document.removeEventListener('webkitfullscreenchange', handler);
    };
  }, []);

  return {
    isUiFullscreen,
    toggleFullscreen,
  };
}
