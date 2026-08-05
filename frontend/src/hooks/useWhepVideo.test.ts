import { describe, expect, it } from 'vitest';
import { filterWhepAnswerCandidates, getDecodedVideoFrameCount, withTimeout } from './useWhepVideo';

const answer = [
  'v=0',
  'a=candidate:one 1 udp 2130706431 192.168.123.222 8189 typ host',
  'a=candidate:two 1 udp 2130706431 192.168.144.104 8189 typ host',
  'a=candidate:three 1 udp 2130706431 192.168.111.60 8189 typ host',
  'a=candidate:four 1 udp 2130706431 10.144.0.4 8189 typ host',
  'a=end-of-candidates',
  '',
].join('\r\n');

describe('filterWhepAnswerCandidates', () => {
  it('keeps only the candidate matching an IPv4 WHEP host', () => {
    const filtered = filterWhepAnswerCandidates(answer, 'http://192.168.144.104:8889/cam/whep');

    expect(filtered).toContain('192.168.144.104 8189');
    expect(filtered).not.toContain('192.168.123.222 8189');
    expect(filtered).not.toContain('192.168.111.60 8189');
    expect(filtered).not.toContain('10.144.0.4 8189');
  });

  it.each([
    ['http://192.168.111.60:8889/cam/whep', '192.168.111.60 8189'],
    ['http://10.144.0.4:8889/cam/whep', '10.144.0.4 8189'],
  ])('selects the candidate for each access network', (url, candidate) => {
    const filtered = filterWhepAnswerCandidates(answer, url);

    expect(filtered).toContain(candidate);
    expect(filtered.match(/^a=candidate:/gm)).toHaveLength(1);
  });

  it('keeps all candidates for hostnames and unavailable addresses', () => {
    expect(filterWhepAnswerCandidates(answer, 'https://botdog.example.com/cam/whep')).toBe(answer);
    expect(filterWhepAnswerCandidates(answer, 'http://192.168.200.10:8889/cam/whep')).toBe(answer);
  });
});

describe('getDecodedVideoFrameCount', () => {
  it('uses actual playback-quality frames when WebRTC state is stale', () => {
    const video = {
      getVideoPlaybackQuality: () => ({ totalVideoFrames: 42 }),
    } as HTMLVideoElement;

    expect(getDecodedVideoFrameCount(video)).toBe(42);
  });

  it('falls back to Chromium legacy decoded frames', () => {
    const video = {
      webkitDecodedFrameCount: 17,
    } as unknown as HTMLVideoElement;

    expect(getDecodedVideoFrameCount(video)).toBe(17);
  });

  it('returns null when the browser exposes no frame counter', () => {
    expect(getDecodedVideoFrameCount({} as HTMLVideoElement)).toBeNull();
  });
});

describe('withTimeout', () => {
  it('returns an operation that completes in time', async () => {
    await expect(withTimeout(Promise.resolve('ok'), 50, 'timed out')).resolves.toBe('ok');
  });

  it('rejects an operation that is stuck', async () => {
    await expect(withTimeout(new Promise(() => undefined), 5, 'negotiation timed out'))
      .rejects.toThrow('negotiation timed out');
  });
});
