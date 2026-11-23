// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { TrackOverlayData } from '../TrackOverlay1';
import { HelmetVoiceButton } from './HelmetVoiceButton';

function detection(label: string, observedAt: number): TrackOverlayData {
  return {
    persons: [], active_bbox: null, command: null, reason: '', state: 'POSE',
    frame_w: 1920, frame_h: 1080, deadband_px: 0,
    anchor_y_stop_ratio: 1, forward_area_ratio: 1,
    person_received_at_ms: observedAt,
    detections: [{ class_name: label, bbox: [0, 0, 40, 40], conf: 0.9 }],
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('HelmetVoiceButton', () => {
  it('loops while head detections are fresh and stops on expiry, disconnection, or disabling', async () => {
    vi.useFakeTimers();
    const source = { start: vi.fn(), stop: vi.fn(), connect: vi.fn(), disconnect: vi.fn(), loop: false };
    const close = vi.fn().mockResolvedValue(undefined);
    const resume = vi.fn().mockResolvedValue(undefined);
    const context = {
      resume, close,
      decodeAudioData: vi.fn().mockResolvedValue({ duration: 3.4 }),
      createBufferSource: vi.fn().mockReturnValue(source),
      destination: {},
    };
    vi.stubGlobal('AudioContext', function () { return context; });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, arrayBuffer: async () => new ArrayBuffer(8),
    }));
    const now = vi.spyOn(performance, 'now').mockReturnValue(10000);
    const view = render(<HelmetVoiceButton overlay={detection('head', 10000)} videoConnected />);
    const button = screen.getByRole('button', { name: '未戴安全帽语音提醒' });
    expect(source.start).not.toHaveBeenCalled();

    view.rerender(<HelmetVoiceButton overlay={detection('helmet', 10000)} videoConnected />);
    await act(async () => { fireEvent.click(button); });
    expect(resume).toHaveBeenCalledOnce();
    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(source.start).not.toHaveBeenCalled();

    view.rerender(<HelmetVoiceButton overlay={detection('head', 8000)} videoConnected />);
    view.rerender(<HelmetVoiceButton overlay={detection('head', 10000)} videoConnected={false} />);
    expect(source.start).not.toHaveBeenCalled();

    view.rerender(<HelmetVoiceButton overlay={detection('head', 10000)} videoConnected />);
    expect(source.start).toHaveBeenCalledTimes(1);
    expect(source.loop).toBe(true);
    for (let observedAt = 11000; observedAt <= 15000; observedAt += 1000) {
      vi.advanceTimersByTime(1000);
      now.mockReturnValue(observedAt);
      view.rerender(<HelmetVoiceButton overlay={detection('head', observedAt)} videoConnected />);
    }
    expect(source.start).toHaveBeenCalledTimes(1);
    expect(source.stop).not.toHaveBeenCalled();

    view.rerender(<HelmetVoiceButton overlay={detection('helmet', 15001)} videoConnected />);
    vi.advanceTimersByTime(1500);
    expect(source.stop).toHaveBeenCalledTimes(1);
    now.mockReturnValue(16500);
    view.rerender(<HelmetVoiceButton overlay={detection('head', 16500)} videoConnected />);
    expect(source.start).toHaveBeenCalledTimes(2);
    view.rerender(<HelmetVoiceButton overlay={detection('head', 16500)} videoConnected={false} />);
    expect(source.stop).toHaveBeenCalledTimes(2);

    now.mockReturnValue(16501);
    view.rerender(<HelmetVoiceButton overlay={detection('head', 16501)} videoConnected />);
    expect(source.start).toHaveBeenCalledTimes(3);
    fireEvent.click(button);
    expect(source.stop).toHaveBeenCalledTimes(3);
    expect(close).toHaveBeenCalledOnce();
    expect(button.getAttribute('aria-pressed')).toBe('false');
  });
});
