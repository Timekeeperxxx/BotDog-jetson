import type { RefObject } from 'react';
import type { AIStatus } from '../../types/event';
import type { AutoTrackHookState } from '../../hooks/useAutoTrack';
import type { TelemetryData } from '../../hooks/useBotDogWebSocket';
import type { TrackOverlayData } from '../TrackOverlay1';
import type { WhepState } from '../../hooks/useWhepVideo';
import type { OmniCameraUrls } from '../../hooks/useCameraSources';

export interface CurrentWhepInfo {
  color: string;
  text: string;
}

export interface CameraVideoProps {
  videoRef: RefObject<HTMLVideoElement | null>;
}

export interface VideoHudProps {
  resolutionChip: string;
  currentWhep: CurrentWhepInfo;
  whepStatus: WhepState;
  telemetry: TelemetryData | null;
  isUiFullscreen: boolean;
  aiStatus: AIStatus | null;
  autoTrackFrames: number;
  isConnected: boolean;
  videoLatencyMs: number | null;
  autoTrack: AutoTrackHookState;
  connectWs: () => void;
  connectWhep: () => void;
  isMissionRunning: boolean;
}

export interface VideoStageProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  isUiFullscreen: boolean;
  toggleFullscreen: () => void;
  trackOverlay: TrackOverlayData | null;
  autoTrackEnabled: boolean;
  guardEnabled: boolean;
  whepStatus: WhepState;
  currentWhep: CurrentWhepInfo;
  videoLatencyMs: number | null;
  videoResolution: { width: number | null; height: number | null };
  resolutionChip: string;
  telemetry: TelemetryData | null;
  isConnected: boolean;
  aiStatus: AIStatus | null;
  autoTrackFrames: number;
  autoTrack: AutoTrackHookState;
  connectWs: () => void;
  connectWhep: () => void;
  isMissionRunning: boolean;
  triggerSnapshot: () => void;
  toggleMission: () => void | Promise<void>;
  frontWhepUrl: string | undefined;
  omniUrls: OmniCameraUrls;
  isRecording?: boolean;
  onToggleRecording?: () => void;
}
