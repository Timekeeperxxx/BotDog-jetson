import { useEffect, type ComponentProps } from 'react';
import { ConsoleRightPanel } from '../console/ConsoleRightPanel';
import { ConsoleStopBar } from '../console/ConsoleStopBar';
import { VideoStage } from '../video/VideoStage';
import { useRobotControl } from '../../hooks/useRobotControl';

export interface ConsolePageProps {
  isUiFullscreen: boolean;
  videoStageProps: ComponentProps<typeof VideoStage>;
  rightPanelProps: Omit<ComponentProps<typeof ConsoleRightPanel>, 'control'>;
}

export function ConsolePage({ isUiFullscreen, videoStageProps, rightPanelProps }: ConsolePageProps) {
  const control = useRobotControl();
  const { isControlling, stopCommand } = control;
  useEffect(() => {
    if (isUiFullscreen && isControlling) stopCommand();
  }, [isUiFullscreen, isControlling, stopCommand]);

  return (
    <div className="console-page flex-1 flex min-h-0 relative">
      <VideoStage {...videoStageProps} />
      {!isUiFullscreen && <ConsoleRightPanel {...rightPanelProps} control={control} />}
      <ConsoleStopBar control={control} />
    </div>
  );
}
