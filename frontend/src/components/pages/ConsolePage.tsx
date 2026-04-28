import type { ComponentProps } from 'react';
import { ConsoleRightPanel } from '../console/ConsoleRightPanel';
import { VideoStage } from '../video/VideoStage';

export interface ConsolePageProps {
  isUiFullscreen: boolean;
  videoStageProps: ComponentProps<typeof VideoStage>;
  rightPanelProps: ComponentProps<typeof ConsoleRightPanel>;
}

export function ConsolePage({ isUiFullscreen, videoStageProps, rightPanelProps }: ConsolePageProps) {
  return (
    <div className="flex-1 flex min-h-0 relative">
      <VideoStage {...videoStageProps} />
      {!isUiFullscreen && <ConsoleRightPanel {...rightPanelProps} />}
    </div>
  );
}
