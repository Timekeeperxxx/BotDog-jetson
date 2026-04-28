import type { CameraVideoProps } from './types';

export function CameraVideo({
  videoRef,
  isMain,
  isPipLarge,
  isPipHidden,
  pipDimensions,
}: CameraVideoProps) {
  return (
    <video
      ref={videoRef}
      autoPlay
      playsInline
      muted
      className="absolute object-cover bg-black transition-all duration-300"
      style={isMain ? {
        inset: 0, width: '100%', height: '100%', zIndex: 1, borderRadius: 0,
      } : {
        bottom: '108px',
        right: '16px',
        top: 'auto',
        left: 'auto',
        width: isPipLarge ? `${pipDimensions.largeWidth}px` : `${pipDimensions.smallWidth}px`,
        height: isPipLarge ? `${pipDimensions.largeHeight}px` : `${pipDimensions.smallHeight}px`,
        zIndex: 21,
        borderRadius: '8px',
        display: isPipHidden ? 'none' : undefined,
      }}
    />
  );
}
