import type { CameraVideoProps } from './types';

export function CameraVideo({ videoRef }: CameraVideoProps) {
  return (
    <video
      ref={videoRef}
      autoPlay
      playsInline
      muted
      className="absolute inset-0 w-full h-full object-cover bg-black z-[1]"
    />
  );
}
