import { apiFetch } from '../api/apiFetch';

export interface AlertReceiptObservation {
  clientId: string;
  receivedAt: number;
  pageVisibleOnReceive: boolean;
  mountedAt?: number;
  pageVisibleOnMount?: boolean;
  cardVisibleOnMount?: boolean;
  firstVisibleAt?: number;
  displayedAt?: number;
  waitingSince?: number;
  visibilityWaitMs: number;
}

const clientId = globalThis.crypto?.randomUUID?.() ?? `page-${Date.now()}-${Math.random().toString(36).slice(2)}`;
let clock: { offset: number; uncertainty: number; sampled: number } | undefined;
let pendingClock: Promise<NonNullable<typeof clock>> | undefined;

async function calibratedClock() {
  if (clock && performance.now() - clock.sampled < 30_000) return clock;
  if (!pendingClock) pendingClock = (async () => {
    const before = performance.now();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20_000);
    let sample: { server_time: string };
    try {
      sample = await apiFetch<{ server_time: string }>('/api/v1/evidence/clock', { cache: 'no-store', signal: controller.signal });
    } finally { clearTimeout(timeout); }
    const after = performance.now();
    const server = Date.parse(sample.server_time);
    if (!Number.isFinite(server) || after - before > 20_000) throw new Error('告警校时失败');
    clock = { offset: server - (before + after) / 2, uncertainty: (after - before) / 2 + 1, sampled: after };
    return clock;
  })().finally(() => { pendingClock = undefined; });
  return pendingClock;
}

type Job = { attempts: number; timer?: ReturnType<typeof setTimeout>; build: (sample: NonNullable<typeof clock>) => Record<string, unknown> };
const pending = new Map<string, Job>();
const observations = new Map<number, AlertReceiptObservation>();

function enqueue(path: string, build: Job['build']) {
  if (pending.has(path)) return;
  if (pending.size >= 512) {
    const oldest = pending.entries().next().value;
    if (oldest) { clearTimeout(oldest[1].timer); pending.delete(oldest[0]); }
  }
  const job: Job = { attempts: 0, build };
  pending.set(path, job);
  const attempt = async () => {
    if (pending.get(path) !== job) return;
    job.attempts += 1;
    try {
      const sample = await calibratedClock();
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10_000);
      try {
        await apiFetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(job.build(sample)), signal: controller.signal });
      } finally { clearTimeout(timeout); }
      if (pending.get(path) === job) pending.delete(path);
    } catch (error) {
      if (pending.get(path) !== job) return;
      if (job.attempts >= 8) {
        pending.delete(path);
        console.error('告警计时回执重试失败', path, error);
        return;
      }
      job.timer = setTimeout(() => { void attempt(); }, Math.min(500 * 2 ** (job.attempts - 1), 30_000));
    }
  };
  void attempt();
}

function iso(at: number, sample: NonNullable<typeof clock>) {
  return new Date(at + sample.offset).toISOString();
}

export function recordAlertReceived(evidenceId: number, receivedAt: number, pageVisible: boolean): AlertReceiptObservation {
  const existing = observations.get(evidenceId);
  if (existing) return existing;
  const observation: AlertReceiptObservation = {
    clientId, receivedAt, pageVisibleOnReceive: pageVisible, visibilityWaitMs: 0,
  };
  observations.set(evidenceId, observation);
  if (observations.size > 1024) observations.delete(observations.keys().next().value!);
  enqueue(`/api/v1/evidence/${evidenceId}/received`, (sample) => ({
    client_id: clientId, received_at: iso(receivedAt, sample),
    page_visible_on_receive: pageVisible, clock_uncertainty_ms: sample.uncertainty,
  }));
  return observation;
}

export function recordAlertDisplayed(evidenceId: number, observation: AlertReceiptObservation) {
  const displayedAt = observation.displayedAt, mountedAt = observation.mountedAt;
  if (displayedAt === undefined || mountedAt === undefined) return;
  // Retries retain the first samples, including after a card is unmounted.
  const measured = { ...observation };
  enqueue(`/api/v1/evidence/${evidenceId}/displayed`, (sample) => ({
    client_id: measured.clientId,
    received_at: iso(measured.receivedAt, sample), mounted_at: iso(mountedAt, sample),
    first_visible_at: measured.firstVisibleAt === undefined ? undefined : iso(measured.firstVisibleAt, sample),
    displayed_at: iso(displayedAt, sample), clock_uncertainty_ms: sample.uncertainty,
    page_visible_on_receive: measured.pageVisibleOnReceive,
    page_visible_on_mount: measured.pageVisibleOnMount, card_visible_on_mount: measured.cardVisibleOnMount,
    receive_to_mount_ms: Math.max(0, mountedAt - measured.receivedAt),
    visibility_wait_ms: measured.visibilityWaitMs,
    visible_render_ms: Math.max(0, displayedAt - mountedAt - measured.visibilityWaitMs),
    receive_to_display_ms: Math.max(0, displayedAt - measured.receivedAt),
  }));
}

export function recordLegacyAlertDisplayed(evidenceId: number, displayedAt: number) {
  enqueue(`/api/v1/evidence/${evidenceId}/displayed`, (sample) => ({
    displayed_at: iso(displayedAt, sample), clock_uncertainty_ms: sample.uncertainty,
  }));
}
