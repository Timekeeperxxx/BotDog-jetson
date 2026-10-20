import type { TrackOverlayData } from '../components/TrackOverlay1';
import type { AlertEvent } from '../types/event';

export const PACKAGE_OBSERVATION_TTL_MS = 750;
export const PACKAGE_CLASSES = new Set(['backpack', 'handbag', 'suitcase', 'luggage', 'parcel']);

type Detection = NonNullable<TrackOverlayData['detections']>[number];
const isPackage = (detection: Detection) => PACKAGE_CLASSES.has(detection.class_name ?? '');

export const hasPackageObservation = (data: TrackOverlayData | null) => Boolean(data?.detections?.some(isPackage));

export function observationAt(now: number, age?: number): number {
  return age === undefined ? now : Number.isFinite(age) && age >= 0 ? now - age : now - PACKAGE_OBSERVATION_TTL_MS;
}

export function observationFresh(at: number | undefined, now: number): boolean {
  return at !== undefined && Number.isFinite(at) && now >= at && now - at < PACKAGE_OBSERVATION_TTL_MS;
}

function validBox(box: unknown): box is number[] {
  return Array.isArray(box) && box.length === 4 && box.every(Number.isFinite)
    && box[2] > box[0] && box[3] > box[1];
}

export function boxesIntersect(a: number[], b: number[]): boolean {
  return validBox(a) && validBox(b)
    && Math.min(a[2], b[2]) > Math.max(a[0], b[0])
    && Math.min(a[3], b[3]) > Math.max(a[1], b[1]);
}

export function freshPersonBoxes(data: TrackOverlayData, now: number): number[][] {
  const notOlder = (frame: number | undefined, at: number | undefined) => (
    Number.isFinite(frame) && Number.isFinite(data.package_frame_received_at_monotonic)
      ? frame! >= data.package_frame_received_at_monotonic!
      : at !== undefined && at >= (data.package_received_at_ms ?? at)
  );
  const persons = observationFresh(data.person_received_at_ms, now)
    && notOlder(data.person_frame_received_at_monotonic, data.person_received_at_ms)
    ? (data.detections ?? data.persons ?? []).filter(d => (d.class_name ?? 'person') === 'person'
      && Number.isFinite(d.conf) && d.conf > 0 && validBox(d.bbox)).map(d => d.bbox) : [];
  const poses = observationFresh(data.pose_received_at_ms, now)
    && notOlder(data.pose_frame_received_at_monotonic, data.pose_received_at_ms)
    ? (data.poses ?? []).filter(p => Number.isFinite(p.confidence) && p.confidence > 0
      && validBox(p.bbox)).map(p => p.bbox) : [];
  // A package-stage pose is a current positive blocker, not a pose-cache update.
  const packagePeople = observationFresh(data.package_received_at_ms, now)
    ? (data.package_person_boxes ?? []).filter(validBox) : [];
  return [...persons, ...poses, ...packagePeople];
}

export function isPackageUpdate(source: Partial<TrackOverlayData>, messageType: string): boolean {
  return source.package_updated ?? (source.stage === 'package'
    || (messageType === 'POSE_OVERLAY' && source.stage === undefined));
}

export function expirePackageObservation(data: TrackOverlayData, now: number): TrackOverlayData {
  if (data.package_received_at_ms === undefined
      || now - data.package_received_at_ms < PACKAGE_OBSERVATION_TTL_MS
      || !data.detections?.some(isPackage)) return data;
  return { ...data, detections: data.detections.filter((detection) => !isPackage(detection)) };
}

export function mergePackageObservation(
  previous: TrackOverlayData | null,
  incoming: TrackOverlayData,
  messageType: 'TRACK_OVERLAY' | 'POSE_OVERLAY',
  now: number,
  source: Partial<TrackOverlayData> = incoming,
): TrackOverlayData {
  const incomingPackages = source.detections?.filter(isPackage) ?? [];
  const older = Number.isFinite(previous?.package_frame_received_at_monotonic)
    && Number.isFinite(source.frame_received_at_monotonic)
    && source.frame_received_at_monotonic! < previous!.package_frame_received_at_monotonic!;
  const sourceSameSize = source.frame_w === incoming.frame_w && source.frame_h === incoming.frame_h;
  const updated = isPackageUpdate(source, messageType) && !older && sourceSameSize;
  const sameSize = previous?.frame_w === incoming.frame_w && previous?.frame_h === incoming.frame_h;
  const oldPackages = sameSize && previous && Number.isFinite(previous.package_received_at_ms)
    ? expirePackageObservation(previous, now).detections?.filter(isPackage) ?? []
    : [];
  const sameFrame = sameSize && Number.isFinite(source.frame_received_at_monotonic)
    && source.frame_received_at_monotonic === previous?.package_frame_received_at_monotonic;
  // Duplicate completion/partial packets cannot renew the same captured sample.
  const observedAt = updated ? sameFrame && Number.isFinite(previous?.package_received_at_ms)
    ? previous!.package_received_at_ms : observationAt(now, source.frame_age_ms)
    : previous?.package_received_at_ms;
  const packages = updated ? incomingPackages : oldPackages;
  const otherDetections = (incoming.detections ?? incoming.persons ?? []).filter((detection) => !isPackage(detection));
  const sampledPeople = updated ? [
    ...(source.detections ?? []).filter(d => (d.class_name ?? 'person') === 'person'
      && Number.isFinite(d.conf) && d.conf > 0 && validBox(d.bbox)).map(d => d.bbox),
    ...(source.stage === 'package' ? source.poses ?? [] : []).filter(p => Number.isFinite(p.confidence)
      && p.confidence > 0 && validBox(p.bbox)).map(p => p.bbox),
  ] : [];
  const clearedIds = updated && (source.stage === 'package' || source.stage === 'complete')
    && Number.isFinite(source.frame_received_at_monotonic)
    && Array.isArray(source.package_overlap_cleared_track_ids)
    ? source.package_overlap_cleared_track_ids.filter(id => Number.isInteger(id) && id >= 0) : [];
  const result: TrackOverlayData = {
    ...incoming,
    detections: incoming.detections === undefined && packages.length === 0
      ? undefined
      : [...otherDetections, ...packages],
    package_received_at_ms: observedAt,
    package_updated: updated,
    package_frame_received_at_monotonic: updated
      ? source.frame_received_at_monotonic : previous?.package_frame_received_at_monotonic,
    package_person_boxes: updated ? [...(sameFrame ? previous?.package_person_boxes ?? [] : []), ...sampledPeople]
      : sameSize ? previous?.package_person_boxes : undefined,
    // Clear evidence belongs to this authoritative sample. Old/partial packets
    // cannot replace it; same-frame completion cannot erase the early clear.
    package_overlap_cleared_track_ids: updated
      ? [...new Set([...(sameFrame ? previous?.package_overlap_cleared_track_ids ?? [] : []), ...clearedIds])]
      : sameSize ? previous?.package_overlap_cleared_track_ids : undefined,
  };
  const fresh = expirePackageObservation(result, now);
  // Only positive current people can suppress a displayed state. Empty/unknown
  // person observations never advance confirmation or restore an old red latch.
  const people = freshPersonBoxes(fresh, now);
  if (!people.length) return fresh;
  return { ...fresh, detections: fresh.detections?.map(detection => (
    isPackage(detection) && people.some(box => boxesIntersect(box, detection.bbox))
      ? { ...detection, package_state: 'overlapping', unattended_seconds: 0 } : detection
  )) };
}

export interface PackageAlertLink {
  alert: AlertEvent;
  trackId: number;
  frame: number;
  observedAt: number;
  bbox: number[];
  width: number;
  height: number;
}

/** Bind an alert only to a timed, identified package; never use fuzzy IoU to dismiss it. */
export function reconcilePackageAlert(
  alert: AlertEvent, link: PackageAlertLink | null, data: TrackOverlayData | null, now: number,
): { link: PackageAlertLink | null; overlapping: boolean } {
  const none = { link: null, overlapping: false };
  if (alert.event_code !== 'E_PACKAGE_ABANDONED' && alert.event_type !== 'PACKAGE_ABANDONED') return none;
  if (!data || !observationFresh(data.package_received_at_ms, now)
      || !Number.isFinite(data.package_frame_received_at_monotonic)
      || typeof alert.track_id !== 'number' || !Number.isInteger(alert.track_id) || alert.track_id < 0) return none;
  const bag = data.detections?.find(d => isPackage(d) && d.track_id === alert.track_id && validBox(d.bbox));
  const frame = data.package_frame_received_at_monotonic!;
  const observedAt = data.package_received_at_ms!;
  if (link?.alert === alert) {
    if (link.trackId !== alert.track_id || link.width !== data.frame_w || link.height !== data.frame_h
        || frame < link.frame || observedAt < link.observedAt
        || (frame - link.frame) * 1000 >= PACKAGE_OBSERVATION_TTL_MS
        || observedAt - link.observedAt >= PACKAGE_OBSERVATION_TTL_MS) return none;
    // A person may hide the current bag. Only the engine's explicit, fresh
    // latch-clear for this already-bound track can dismiss without a bag box.
    if (data.package_overlap_cleared_track_ids?.includes(link.trackId)) {
      return { link: { ...link, frame, observedAt }, overlapping: true };
    }
    if (!bag || !boxesIntersect(link.bbox, bag.bbox)) return none;
  } else {
    if (!bag) return none; // No new association from a bare cleared ID.
    // The producer supplies event.observed_at in the same monotonic clock as
    // the package overlay. Older alerts without this exact identity stay visible.
    const exactFrame = typeof alert.frame_received_at_monotonic === 'number'
      && Number.isFinite(alert.frame_received_at_monotonic) && alert.frame_received_at_monotonic === frame;
    if (!exactFrame) return none;
  }
  if (!bag) return none;
  const next: PackageAlertLink = { alert, trackId: alert.track_id, frame, observedAt,
    bbox: bag.bbox, width: data.frame_w, height: data.frame_h };
  return { link: next, overlapping: freshPersonBoxes(data, now).some(box => boxesIntersect(box, bag.bbox)) };
}
