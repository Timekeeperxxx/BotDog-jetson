import type { RefObject } from 'react';
import type { AIStatus } from '../../types/event';
import type { AutoTrackHookState } from '../../hooks/useAutoTrack';
import type { TelemetryData } from '../../hooks/useBotDogWebSocket';
import type { TrackOverlayData } from '../TrackOverlay1';
import type { WhepState } from '../../hooks/useWhepVideo';

export interface CurrentWhepInfo {
  color: string;
  text: string;
}

export interface PipDimensions {
  smallWidth: number;
  smallHeight: number;
  largeWidth: number;
  largeHeight: number;
}

export interface CameraVideoProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  isMain: boolean;
  isPipLarge: boolean;
  isPipHidden: boolean;
  pipDimensions: PipDimensions;
}

export interface PipControlsProps {
  isPipLarge: boolean;
  isPipHidden: boolean;
  pipLabel: string;
  pipStatus: WhepState;
  pipDimensions: PipDimensions;
  onTogglePipSize: () => void;
  onTogglePipHidden: () => void;
  onSwapCamera: () => void;
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
  videoRef2: RefObject<HTMLVideoElement | null>;
  isCamSwapped: boolean;
  onSwapCamera: () => void;
  isPipLarge: boolean;
  onTogglePipSize: () => void;
  isPipHidden: boolean;
  onTogglePipHidden: () => void;
  isUiFullscreen: boolean;
  toggleFullscreen: () => void;
  trackOverlay: TrackOverlayData | null;
  autoTrackEnabled: boolean;
  guardEnabled: boolean;
  isZoneDrawing: boolean;
  onToggleZoneDrawing: () => void;
  whepStatus: WhepState;
  whepStatus2: WhepState;
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
  connectWhep2: () => void;
  isMissionRunning: boolean;
  triggerSnapshot: () => void;
  toggleMission: () => void | Promise<void>;
}
