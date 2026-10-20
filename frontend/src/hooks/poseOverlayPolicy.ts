import type { TrackOverlayData } from '../components/TrackOverlay1';
import { observationAt } from './packageOverlayObservation';

export type PoseOverlayPayload = Pick<
  TrackOverlayData,
  'frame_w' | 'frame_h' | 'detections' | 'poses' | 'keypoint_confidence' | 'active_actions'
> & Partial<Pick<TrackOverlayData, 'stage' | 'frame_received_at_monotonic' | 'frame_age_ms'
  | 'package_updated' | 'pose_updated' | 'package_overlap_cleared_track_ids'>>;

export const FACE_RESULT_DISPLAY_MAX_AGE_MS = 750;
type Detection = NonNullable<TrackOverlayData['detections']>[number];

function overlap(a: number[], b: number[]): number {
  if (a.length !== 4 || b.length !== 4) return 0;
  const area = (box: number[]) => Math.max(0, box[2] - box[0]) * Math.max(0, box[3] - box[1]);
  const intersection = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]))
    * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  const union = area(a) + area(b) - intersection;
  return union > 0 ? intersection / union : 0;
}

function carryFaceResult(incoming: Detection, previous: Detection): Detection {
  return {
    ...incoming,
    track_id: incoming.track_id !== undefined && incoming.track_id >= 0
      ? incoming.track_id : previous.track_id,
    identity_id: previous.identity_id,
    display_name: previous.display_name,
    face_status: previous.face_status,
    face_score: previous.face_score,
    is_stranger: previous.is_stranger,
    safety_status: previous.safety_status,
    face_result_received_at_ms: previous.face_result_received_at_ms,
  };
}

/** Intermediate position messages update geometry; only completed results update identity. */
export function mergePoseOverlay(
  previous: TrackOverlayData | null,
  payload: PoseOverlayPayload,
  now: number,
): TrackOverlayData {
  if (previous?.frame_received_at_monotonic !== undefined
      && payload.frame_received_at_monotonic !== undefined
      && payload.frame_received_at_monotonic < previous.frame_received_at_monotonic) return previous;

  const early = payload.stage === 'location' || payload.stage === 'pose_location' || payload.stage === 'package';
  const sameDimensions = previous?.frame_w === payload.frame_w && previous?.frame_h === payload.frame_h;
  const candidates = sameDimensions ? (previous?.detections ?? []).filter(item => (
    (item.class_name ?? 'person') === 'person'
    && item.face_result_received_at_ms !== undefined
    && now - item.face_result_received_at_ms < FACE_RESULT_DISPLAY_MAX_AGE_MS
  )) : [];
  const used = new Set<Detection>();
  const currentIds = new Set((payload.detections ?? []).map(item => item.track_id));
  const detections = payload.detections?.map(item => {
    if ((item.class_name ?? 'person') !== 'person') return item;
    if (!early) return { ...item, face_result_received_at_ms: now };
    let matching = candidates.find(candidate => !used.has(candidate)
      && item.track_id !== undefined && item.track_id >= 0 && item.track_id === candidate.track_id);
    // Early main-detector results can arrive before a cross-frame ID is assigned.
    // Use one-to-one spatial association only for these unassigned results.
    if (!matching && (item.track_id === undefined || item.track_id < 0)) {
      matching = candidates
        .filter(candidate => !used.has(candidate) && !currentIds.has(candidate.track_id))
        .filter(candidate => overlap(item.bbox, candidate.bbox) >= 0.5)
        .sort((a, b) => overlap(item.bbox, b.bbox) - overlap(item.bbox, a.bbox))[0];
    }
    if (!matching) return item;
    used.add(matching);
    return carryFaceResult(item, matching);
  });

  const positionOnly = payload.stage === 'location' || payload.stage === 'package';
  // Completed packets can contain cached skeletons. Only a fresh pose stage
  // (or an explicit producer marker) advances the pose observation clock.
  const poseUpdated = !positionOnly && (payload.stage === 'pose_location' || payload.pose_updated === true
    || (payload.stage === undefined && Array.isArray(payload.poses)));
  const observedAt = observationAt(now, payload.frame_age_ms);
  return {
    active_bbox: previous?.active_bbox ?? null,
    command: previous?.command ?? null,
    reason: previous?.reason ?? '',
    state: previous?.state ?? 'POSE',
    deadband_px: previous?.deadband_px ?? 0,
    anchor_y_stop_ratio: previous?.anchor_y_stop_ratio ?? 1,
    forward_area_ratio: previous?.forward_area_ratio ?? 1,
    ...previous,
    ...payload,
    detections: detections ?? [],
    persons: (detections ?? []).filter(d => (d.class_name ?? 'person') === 'person')
      .map(d => ({ ...d, is_stranger: d.is_stranger ?? undefined })),
    poses: poseUpdated ? payload.poses : sameDimensions ? previous?.poses : undefined,
    active_actions: poseUpdated ? payload.active_actions : sameDimensions ? previous?.active_actions : undefined,
    keypoint_confidence: poseUpdated ? payload.keypoint_confidence
      : sameDimensions ? previous?.keypoint_confidence : undefined,
    received_at_ms: now,
    person_received_at_ms: Array.isArray(payload.detections) ? observedAt : undefined,
    person_frame_received_at_monotonic: payload.frame_received_at_monotonic,
    pose_received_at_ms: poseUpdated ? observedAt : sameDimensions ? previous?.pose_received_at_ms : undefined,
    pose_frame_received_at_monotonic: poseUpdated ? payload.frame_received_at_monotonic
      : sameDimensions ? previous?.pose_frame_received_at_monotonic : undefined,
  };
}
