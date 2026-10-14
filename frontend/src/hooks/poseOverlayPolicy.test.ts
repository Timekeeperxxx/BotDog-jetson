import { describe, expect, it } from 'vitest';
import { mergePoseOverlay, type PoseOverlayPayload } from './poseOverlayPolicy';

const recognized = (): PoseOverlayPayload => ({
  stage: 'complete', frame_w: 640, frame_h: 360,
  frame_received_at_monotonic: 1,
  detections: [{ class_name: 'person', track_id: 6, bbox: [220, 2, 640, 330],
    conf: .9, face_status: 'recognized', identity_id: 2, display_name: '罗浩文',
    face_score: .67, is_stranger: false }],
  poses: [], active_actions: [],
});
const early = (stage: 'location' | 'pose_location' = 'pose_location'): PoseOverlayPayload => ({
  ...recognized(), stage, frame_received_at_monotonic: 2,
  detections: [{ class_name: 'person', track_id: 6, bbox: [223, 3, 640, 328],
    conf: .92, face_status: 'pending', identity_id: null, display_name: null, is_stranger: null }],
});

describe('incremental person overlays', () => {
  it('moves the box immediately without changing a completed name or box color', () => {
    const previous = mergePoseOverlay(null, recognized(), 100);
    const incoming = early();
    const merged = mergePoseOverlay(previous, incoming, 200);
    expect(merged.detections?.[0]).toMatchObject({ bbox: [223, 3, 640, 328], conf: .92,
      face_status: 'recognized', display_name: '罗浩文', is_stranger: false, face_result_received_at_ms: 100 });
    expect(incoming.detections?.[0].face_status).toBe('pending');
  });

  it('preserves the visible ID for an unassigned early box, without modifying the message', () => {
    const previous = mergePoseOverlay(null, recognized(), 100);
    const incoming = early('location');
    incoming.detections![0].track_id = -1;
    const merged = mergePoseOverlay(previous, incoming, 200);
    expect(merged.detections?.[0].track_id).toBe(6);
    expect(merged.detections?.[0].display_name).toBe('罗浩文');
    expect(incoming.detections?.[0].track_id).toBe(-1);
  });

  it('does not give a different current track ID a previous person identity', () => {
    const previous = mergePoseOverlay(null, recognized(), 100);
    const incoming = early();
    incoming.detections![0].track_id = 7;
    expect(mergePoseOverlay(previous, incoming, 200).detections?.[0].face_status).toBe('pending');
  });

  it('does not extend identity freshness through repeated early messages', () => {
    const first = mergePoseOverlay(null, recognized(), 100);
    const repeated = mergePoseOverlay(first, early(), 500);
    expect(mergePoseOverlay(repeated, early(), 850).detections?.[0].face_status).toBe('pending');
  });

  it.each(['pending', 'unknown', 'no_face', 'unavailable'] as const)('uses a completed %s result immediately', status => {
    const first = mergePoseOverlay(null, recognized(), 100);
    const completion = early();
    completion.stage = 'complete';
    completion.detections![0].face_status = status;
    completion.detections![0].is_stranger = true;
    const merged = mergePoseOverlay(first, completion, 200);
    expect(merged.detections?.[0]).toMatchObject({ face_status: status, display_name: null, identity_id: null, is_stranger: true });
  });

  it('clears an absent person immediately and does not invent a held box', () => {
    const incoming = { ...recognized(), detections: [] };
    expect(mergePoseOverlay(mergePoseOverlay(null, recognized(), 100), incoming, 200).detections).toEqual([]);
  });

  it('does not reuse results across video dimension changes', () => {
    const incoming = { ...early(), frame_w: 1280, frame_h: 720 };
    expect(mergePoseOverlay(mergePoseOverlay(null, recognized(), 100), incoming, 200).detections?.[0].face_status).toBe('pending');
  });

  it('ignores late results from an older source frame', () => {
    const first = mergePoseOverlay(null, early(), 100);
    expect(mergePoseOverlay(first, recognized(), 200)).toBe(first);
  });

  it('keeps skeleton freshness tied to pose updates rather than raw position messages', () => {
    const first = mergePoseOverlay(null, recognized(), 100);
    const incoming = early('location');
    expect(mergePoseOverlay(first, incoming, 200).pose_received_at_ms).toBe(100);
  });
});
